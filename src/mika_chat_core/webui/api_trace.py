"""WebUI trace APIs (agent traces)."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, Response

from ..config import Config
from ..observability.trace_store import get_trace_store
from ..runtime import get_config as get_runtime_config
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper


def create_trace_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/trace",
        tags=["mika-webui-trace"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.get("/recent")
    async def list_recent_traces(session_key: str = "", limit: int = 20) -> Dict[str, Any]:
        store = get_trace_store()
        items = await store.list_recent(session_key=str(session_key or "").strip(), limit=int(limit or 20))
        return BaseRouteHelper.ok({"items": items})

    @router.get("/{request_id}")
    async def get_trace(request_id: str) -> Dict[str, Any]:
        rid = str(request_id or "").strip()
        if not rid:
            return BaseRouteHelper.error_response("request_id is required")
        store = get_trace_store()
        row = await store.get_trace(rid)
        if row is None:
            return BaseRouteHelper.ok({"exists": False, "request_id": rid})
        return BaseRouteHelper.ok(
            {
                "exists": True,
                "request_id": row.request_id,
                "session_key": row.session_key,
                "user_id": row.user_id,
                "group_id": row.group_id,
                "created_at": row.created_at,
                "plan": row.plan,
                "events": row.events,
            }
        )

    @router.get("/{request_id}/export")
    async def export_trace(request_id: str) -> Response:
        rid = str(request_id or "").strip()
        store = get_trace_store()
        row = await store.get_trace(rid)
        payload: dict[str, Any]
        if row is None:
            payload = {"exists": False, "request_id": rid}
        else:
            payload = {
                "exists": True,
                "request_id": row.request_id,
                "session_key": row.session_key,
                "user_id": row.user_id,
                "group_id": row.group_id,
                "created_at": row.created_at,
                "plan": row.plan,
                "events": row.events,
            }
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=trace-{rid or 'unknown'}.json"},
        )

    return router


__all__ = ["create_trace_router"]

