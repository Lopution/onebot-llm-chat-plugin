"""WebUI persona CRUD APIs."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..config import Config
from ..persona.persona_manager import get_persona_manager
from ..runtime import get_client as get_runtime_client
from ..runtime import get_config as get_runtime_config
from ..utils.prompt_loader import get_character_name, get_system_prompt, load_error_messages
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper


class PersonaPayload(BaseModel):
    name: str = Field(min_length=1)
    character_prompt: str = Field(min_length=1)
    dialogue_examples: List[Dict[str, Any]] = Field(default_factory=list)
    error_messages: Dict[str, str] = Field(default_factory=dict)
    is_active: bool = False
    temperature_override: Optional[float] = None
    model_override: str = ""


class PersonaPatchPayload(BaseModel):
    name: Optional[str] = None
    character_prompt: Optional[str] = None
    dialogue_examples: Optional[List[Dict[str, Any]]] = None
    error_messages: Optional[Dict[str, str]] = None
    is_active: Optional[bool] = None
    temperature_override: Optional[float] = None
    model_override: Optional[str] = None


def _refresh_runtime_prompt(settings_getter: Callable[[], Config]) -> None:
    """更新运行时 client 的人设提示词。"""
    try:
        cfg = settings_getter()
        prompt_file = str(getattr(cfg, "mika_prompt_file", "system.yaml") or "system.yaml")
        client = get_runtime_client()
        client.system_prompt = get_system_prompt(
            prompt_file=prompt_file,
            master_name=str(getattr(cfg, "mika_master_name", "Sensei") or "Sensei"),
        )
        client.character_name = get_character_name(prompt_file)
        error_messages = load_error_messages(prompt_file)
        client.error_messages = error_messages if error_messages else {}
    except Exception:
        # client 未初始化或提示词更新失败时，不阻断 CRUD。
        return


def create_persona_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/persona",
        tags=["mika-webui-persona"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.get("")
    async def list_personas() -> Dict[str, Any]:
        manager = get_persona_manager()
        await manager.init_table()
        items = [item.to_dict() for item in await manager.list_personas()]
        return BaseRouteHelper.ok(items)

    @router.get("/active")
    async def get_active_persona() -> Dict[str, Any]:
        manager = get_persona_manager()
        await manager.init_table()
        active = await manager.get_active_persona()
        return BaseRouteHelper.ok(active.to_dict() if active else None)

    @router.post("")
    async def create_persona(payload: PersonaPayload):
        manager = get_persona_manager()
        await manager.init_table()
        try:
            created = await manager.create_persona(
                name=payload.name,
                character_prompt=payload.character_prompt,
                dialogue_examples=payload.dialogue_examples,
                error_messages=payload.error_messages,
                is_active=payload.is_active,
                temperature_override=payload.temperature_override,
                model_override=payload.model_override,
            )
        except ValueError as exc:
            return BaseRouteHelper.error_response(str(exc), status_code=400)
        _refresh_runtime_prompt(settings_getter)
        return BaseRouteHelper.ok(created.to_dict())

    @router.put("/{persona_id}")
    async def update_persona(persona_id: int, payload: PersonaPatchPayload):
        manager = get_persona_manager()
        await manager.init_table()
        try:
            updated = await manager.update_persona(
                int(persona_id),
                name=payload.name,
                character_prompt=payload.character_prompt,
                dialogue_examples=payload.dialogue_examples,
                error_messages=payload.error_messages,
                is_active=payload.is_active,
                temperature_override=payload.temperature_override,
                model_override=payload.model_override,
            )
        except ValueError as exc:
            return BaseRouteHelper.error_response(str(exc), status_code=400)
        if updated is None:
            return BaseRouteHelper.error_response("persona not found", status_code=404)
        _refresh_runtime_prompt(settings_getter)
        return BaseRouteHelper.ok(updated.to_dict())

    @router.post("/{persona_id}/activate")
    async def activate_persona(persona_id: int):
        manager = get_persona_manager()
        await manager.init_table()
        ok = await manager.set_active(int(persona_id))
        if not ok:
            return BaseRouteHelper.error_response("persona not found", status_code=404)
        _refresh_runtime_prompt(settings_getter)
        active = await manager.get_active_persona()
        return BaseRouteHelper.ok(active.to_dict() if active else None)

    @router.delete("/{persona_id}")
    async def delete_persona(persona_id: int):
        manager = get_persona_manager()
        await manager.init_table()
        deleted = await manager.delete_persona(int(persona_id))
        if not deleted:
            return BaseRouteHelper.error_response("persona not found", status_code=404)
        _refresh_runtime_prompt(settings_getter)
        return BaseRouteHelper.ok({"ok": True})

    return router


__all__ = ["PersonaPayload", "PersonaPatchPayload", "create_persona_router"]

