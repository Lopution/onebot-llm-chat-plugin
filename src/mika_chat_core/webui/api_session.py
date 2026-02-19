"""WebUI session management APIs."""

from __future__ import annotations

from typing import Any, Callable, Dict

from fastapi import APIRouter, Depends

from ..config import Config
from ..runtime import get_config as get_runtime_config
from ..utils.context_store import get_context_store
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper


def create_session_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/session",
        tags=["mika-webui-session"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.get("")
    async def list_sessions(
        page: int = 1,
        page_size: int = 20,
        query: str = "",
    ) -> Dict[str, Any]:
        store = get_context_store()
        data = await store.list_sessions(query=query, page=page, page_size=page_size)
        return BaseRouteHelper.ok(data)

    @router.get("/{session_key:path}")
    async def get_session(session_key: str, preview_limit: int = 5) -> Dict[str, Any]:
        resolved_key = str(session_key or "").strip()
        if not resolved_key:
            return BaseRouteHelper.error_response("session_key is required")
        store = get_context_store()
        data = await store.get_session_stats(resolved_key, preview_limit=preview_limit)
        if not bool(data.get("exists", False)):
            return BaseRouteHelper.error_response(
                "session not found",
                status_code=404,
                data={"session_key": resolved_key},
            )
        return BaseRouteHelper.ok(data)

    @router.delete("/{session_key:path}")
    async def clear_session(
        session_key: str,
        purge_archive: bool = True,
        purge_topic_state: bool = True,
    ) -> Dict[str, Any]:
        resolved_key = str(session_key or "").strip()
        if not resolved_key:
            return BaseRouteHelper.error_response("session_key is required")
        store = get_context_store()
        deleted = await store.clear_session(
            resolved_key,
            purge_archive=bool(purge_archive),
            purge_topic_state=bool(purge_topic_state),
        )
        return BaseRouteHelper.ok({"ok": True, "session_key": resolved_key, "deleted": deleted})

    return router


__all__ = ["create_session_router"]
