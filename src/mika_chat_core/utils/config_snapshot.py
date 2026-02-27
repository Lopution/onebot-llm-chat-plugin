"""Effective config snapshot helpers.

Used by WebUI to show a masked view of the runtime config, plus derived values
and audit warnings.
"""

from __future__ import annotations

from typing import Any, Dict

from .config_audit import audit_config


_MASK = "••••••••"


def _is_secret_key(key: str) -> bool:
    k = str(key or "").strip().lower()
    if not k:
        return False

    # Explicit sensitive suffixes (avoid matching non-secret "tokens" budgets etc).
    if k.endswith("_api_key") or k.endswith("_api_key_list"):
        return True
    if k.endswith("_service_token") or k.endswith("_webui_token") or k.endswith("_token"):
        return True
    if k.endswith("_headers_json"):
        return True

    # Known special-case fields.
    if k in {"llm_api_key", "llm_api_key_list", "search_api_key", "mika_core_service_token", "mika_webui_token"}:
        return True

    return False


def _mask_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        # Preserve "is set" signal without leaking content.
        return [_MASK] * (len(list(value)) if value else 0)
    text = str(value or "").strip()
    if not text:
        return ""
    return _MASK


def mask_config_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
    masked: Dict[str, Any] = {}
    for key, value in dict(raw or {}).items():
        if _is_secret_key(str(key)):
            masked[key] = _mask_value(value)
        else:
            masked[key] = value
    return masked


def build_effective_config_snapshot(cfg: Any) -> Dict[str, Any]:
    """Build a json-friendly snapshot for WebUI/API."""
    raw_cfg: Dict[str, Any] = {}
    try:
        raw_cfg = dict(getattr(cfg, "model_dump")())  # type: ignore[misc]
    except Exception:
        try:
            raw_cfg = dict(cfg.__dict__)
        except Exception:
            raw_cfg = {}

    masked_cfg = mask_config_dict(raw_cfg)

    # Derived views (masked).
    derived: Dict[str, Any] = {}
    try:
        llm_cfg = dict(getattr(cfg, "get_llm_config")())
        llm_cfg["api_keys"] = [_MASK] * len(list(llm_cfg.get("api_keys") or []))
        derived["llm"] = llm_cfg
    except Exception:
        pass
    try:
        search_cfg = dict(getattr(cfg, "get_search_provider_config")())
        if "api_key" in search_cfg:
            search_cfg["api_key"] = _MASK if str(search_cfg.get("api_key") or "").strip() else ""
        derived["search"] = search_cfg
    except Exception:
        pass
    try:
        derived["core_runtime"] = dict(getattr(cfg, "get_core_runtime_config")())
        if "service_token" in derived["core_runtime"]:
            derived["core_runtime"]["service_token"] = (
                _MASK if str(derived["core_runtime"].get("service_token") or "").strip() else ""
            )
    except Exception:
        pass

    warnings = [item.to_dict() for item in audit_config(cfg)]

    profile = ""
    try:
        profile = str(getattr(cfg, "mika_profile", "") or "").strip().lower()
    except Exception:
        profile = ""

    return {
        "profile": profile,
        "config": masked_cfg,
        "derived": derived,
        "warnings": warnings,
    }


__all__ = ["build_effective_config_snapshot", "mask_config_dict"]

