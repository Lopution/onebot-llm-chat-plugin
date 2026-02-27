"""WebUI config APIs.

This module exposes:
- read/write `.env`-backed config via WebUI
- export/import for backup
- effective config snapshot for debugging

Rules:
- No silent legacy-key compatibility (removed keys fail fast in `Config`).
- Secret fields are masked on GET/export unless `include_secrets=true`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from fastapi import APIRouter, Depends

from ..config import Config
from ..runtime import get_config as get_runtime_config
from ..runtime import set_config as set_runtime_config
from ..utils.config_snapshot import build_effective_config_snapshot
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper
from .config_env import (
    build_config_from_env_file,
    collect_updates,
    export_config_values,
    field_default,
    field_kind,
    resolve_env_path,
    sync_config_instance,
    write_env_updates,
)
from .config_schema import (
    CONFIG_FIELD_META,
    CONFIG_SECTIONS,
    CONFIG_UI_SCHEMA,
    SECRET_PLACEHOLDER,
    env_key_for_field,
)

_log = logging.getLogger(__name__)


def _mask_secret_value(raw_value: Any) -> Any:
    return SECRET_PLACEHOLDER if str(raw_value or "").strip() else ""


def _build_field_info(config: Config, field_schema: Dict[str, Any]) -> Dict[str, Any] | None:
    key = str(field_schema.get("key") or "")
    if not key or key not in Config.__annotations__:
        return None

    meta = {k: v for k, v in field_schema.items() if k != "key"}
    raw_value = getattr(config, key, None)
    display_value = _mask_secret_value(raw_value) if meta.get("secret") else raw_value

    info: Dict[str, Any] = {
        "key": key,
        "value": display_value,
        "type": field_kind(key),
        "description": meta.get("description", ""),
        "hint": meta.get("hint", ""),
        "env_key": env_key_for_field(key),
        "default": field_default(key),
    }
    if "options" in meta:
        info["options"] = meta["options"]
    if "labels" in meta:
        info["labels"] = meta["labels"]
    if meta.get("secret"):
        info["secret"] = True
    if meta.get("advanced"):
        info["advanced"] = True
    return info


def _build_sections_payload(config: Config) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for section in CONFIG_UI_SCHEMA:
        fields: List[Dict[str, Any]] = []
        for field_schema in section.get("fields", []):
            info = _build_field_info(config, dict(field_schema or {}))
            if info is not None:
                fields.append(info)
        sections.append({"name": section["name"], "fields": fields})
    return sections


def create_config_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(prefix="/config", tags=["mika-webui-config"], dependencies=[Depends(auth_dependency)])

    @router.get("/env-path")
    async def config_env_path() -> Dict[str, str]:
        return BaseRouteHelper.ok({"path": str(resolve_env_path())})

    @router.get("")
    async def get_config_values() -> Dict[str, Any]:
        return BaseRouteHelper.ok({"sections": _build_sections_payload(settings_getter())})

    @router.get("/effective")
    async def get_effective_config_snapshot() -> Dict[str, Any]:
        config = settings_getter()
        try:
            snapshot = build_effective_config_snapshot(config)
        except Exception as exc:
            return BaseRouteHelper.error_response(f"snapshot failed: {exc}")
        return BaseRouteHelper.ok(snapshot)

    @router.put("")
    async def update_config_values(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return BaseRouteHelper.error_response("payload must be an object")
        current_config = settings_getter()
        updates, error = collect_updates(payload, current_config=current_config)
        if error:
            return BaseRouteHelper.error_response(error)
        if not updates:
            return BaseRouteHelper.ok({"ok": True, "updated_keys": [], "restart_required": False})

        env_path = resolve_env_path()
        write_env_updates(env_path, updates)

        for key, value in updates.items():
            try:
                setattr(current_config, key, value)
            except Exception:
                _log.debug("setattr(%s, %s) failed, skipping", type(current_config).__name__, key, exc_info=True)
        set_runtime_config(current_config)

        return BaseRouteHelper.ok({"ok": True, "updated_keys": sorted(updates.keys()), "restart_required": True})

    @router.post("/reload")
    async def reload_config_values() -> Dict[str, Any]:
        env_path = resolve_env_path()
        current_config = settings_getter()
        try:
            new_config = build_config_from_env_file(env_path, current_config)
        except Exception as exc:
            return BaseRouteHelper.error_response(f"reload failed: {exc}")
        sync_config_instance(current_config, new_config)
        set_runtime_config(current_config)
        return BaseRouteHelper.ok({"ok": True, "env_path": str(env_path), "reloaded": True})

    @router.get("/export")
    async def export_config(include_secrets: bool = False) -> Dict[str, Any]:
        config = settings_getter()
        return BaseRouteHelper.ok(
            {
                "config": export_config_values(config, include_secrets=bool(include_secrets)),
                "env_path": str(resolve_env_path()),
                "include_secrets": bool(include_secrets),
            }
        )

    @router.post("/import")
    async def import_config(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return BaseRouteHelper.error_response("payload must be an object")

        if isinstance(payload.get("config"), dict):
            config_payload = dict(payload.get("config") or {})
            apply_runtime = bool(payload.get("apply_runtime", True))
        else:
            config_payload = dict(payload)
            apply_runtime = True

        current_config = settings_getter()
        updates, error = collect_updates(config_payload, current_config=current_config)
        if error:
            return BaseRouteHelper.error_response(error)
        if not updates:
            return BaseRouteHelper.ok({"ok": True, "updated_keys": [], "applied_runtime": False})

        env_path = resolve_env_path()
        write_env_updates(env_path, updates)

        if apply_runtime:
            for key, value in updates.items():
                try:
                    setattr(current_config, key, value)
                except Exception:
                    pass
            set_runtime_config(current_config)

        return BaseRouteHelper.ok(
            {
                "ok": True,
                "updated_keys": sorted(updates.keys()),
                "applied_runtime": bool(apply_runtime),
                "restart_required": True,
            }
        )

    return router


__all__ = [
    "CONFIG_FIELD_META",
    "CONFIG_SECTIONS",
    "CONFIG_UI_SCHEMA",
    "create_config_router",
]
