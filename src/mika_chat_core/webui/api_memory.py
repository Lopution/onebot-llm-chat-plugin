"""WebUI memory APIs."""

from __future__ import annotations

from typing import Any, Callable, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import Config
from ..runtime import get_config as get_runtime_config
from ..utils.memory_store import get_memory_store
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper


class MemoryCleanupPayload(BaseModel):
    max_age_days: int = 90


def create_memory_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/memory",
        tags=["mika-webui-memory"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.get("/sessions")
    async def list_memory_sessions() -> Dict[str, Any]:
        store = get_memory_store()
        await store.init_table()
        return BaseRouteHelper.ok(await store.list_sessions())

    @router.get("/facts")
    async def list_memory_facts(session_key: str):
        resolved = str(session_key or "").strip()
        if not resolved:
            return BaseRouteHelper.error_response("session_key is required")
        store = get_memory_store()
        await store.init_table()
        return BaseRouteHelper.ok(await store.list_facts(resolved))

    @router.delete("/{memory_id}")
    async def delete_memory_fact(memory_id: int) -> Dict[str, Any]:
        store = get_memory_store()
        await store.init_table()
        ok = await store.delete_memory(int(memory_id))
        return BaseRouteHelper.ok({"ok": ok})

    @router.post("/cleanup")
    async def cleanup_memory(payload: MemoryCleanupPayload) -> Dict[str, Any]:
        max_age = max(1, int(payload.max_age_days))
        store = get_memory_store()
        await store.init_table()
        deleted = await store.delete_old_memories(max_age_days=max_age)
        return BaseRouteHelper.ok({"ok": True, "deleted": int(deleted)})

    return router


__all__ = ["MemoryCleanupPayload", "create_memory_router"]
