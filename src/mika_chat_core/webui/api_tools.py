"""WebUI tools management APIs."""

from __future__ import annotations

from typing import Any, Callable, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import Config
from ..runtime import get_config as get_runtime_config
from ..tools_registry import get_tool_registry
from ..utils.tool_state_store import get_tool_state_store
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper


class ToolTogglePayload(BaseModel):
    enabled: bool


def create_tools_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/tools",
        tags=["mika-webui-tools"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.get("")
    async def list_tools(include_disabled: bool = True) -> Dict[str, Any]:
        registry = get_tool_registry()
        tools = [
            {
                "name": item.name,
                "description": item.description,
                "source": item.source,
                "enabled": bool(item.enabled),
                "parameters": dict(item.parameters or {}),
                "meta": dict(item.meta or {}),
            }
            for item in registry.list_tools(include_disabled=bool(include_disabled))
        ]
        return BaseRouteHelper.ok(
            {
                "tools": tools,
                "total": len(tools),
                "enabled_total": sum(1 for item in tools if item["enabled"]),
            }
        )

    @router.post("/{tool_name}/toggle")
    async def toggle_tool(tool_name: str, payload: ToolTogglePayload) -> Dict[str, Any]:
        name = str(tool_name or "").strip()
        if not name:
            return BaseRouteHelper.error_response("tool_name is required")

        registry = get_tool_registry()
        updated = registry.set_enabled(name, payload.enabled)
        if not updated:
            return BaseRouteHelper.error_response("tool not found", status_code=404)

        store = get_tool_state_store()
        await store.set_enabled(name, payload.enabled)
        item = registry.get(name)
        return BaseRouteHelper.ok(
            {
                "name": name,
                "enabled": bool(item.enabled if item is not None else payload.enabled),
                "persisted": True,
            }
        )

    return router


__all__ = ["ToolTogglePayload", "create_tools_router"]

