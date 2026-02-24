"""WebUI log APIs (history + live SSE)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, Iterable, List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..config import Config
from ..infra.log_broker import get_log_broker
from ..runtime import get_config as get_runtime_config
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper


def _format_log_sse(event: Dict[str, Any]) -> str:
    payload = json.dumps(event, ensure_ascii=False)
    return f"id: {event.get('id', 0)}\nevent: log\ndata: {payload}\n\n"


_LOG_LEVEL_ORDER = {
    "DEBUG": 10,
    "INFO": 20,
    "SUCCESS": 20,
    "WARNING": 30,
    "ERROR": 40,
    "EXCEPTION": 40,
    "CRITICAL": 50,
}


def _normalize_min_level(value: str | None) -> str:
    normalized = str(value or "INFO").strip().upper()
    if normalized not in _LOG_LEVEL_ORDER:
        return "INFO"
    return normalized


def _level_passes(level: str | None, minimum_level: str) -> bool:
    current = _LOG_LEVEL_ORDER.get(str(level or "INFO").strip().upper(), 20)
    minimum = _LOG_LEVEL_ORDER.get(minimum_level, 20)
    return current >= minimum


def _filter_events(
    events: Iterable[Dict[str, Any]],
    *,
    minimum_level: str,
    limit: int,
) -> List[Dict[str, Any]]:
    filtered = [event for event in events if _level_passes(str(event.get("level", "")), minimum_level)]
    max_items = max(1, min(int(limit or 100), 1000))
    if len(filtered) > max_items:
        filtered = filtered[-max_items:]
    return filtered


def create_log_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/log",
        tags=["mika-webui-log"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.get("/history")
    async def log_history(limit: int = 100, since_id: int = 0, min_level: str = "INFO") -> Dict[str, Any]:
        broker = get_log_broker()
        normalized_level = _normalize_min_level(min_level)
        raw_events = broker.history(limit=min(max(int(limit or 100) * 5, 200), 1000), since_id=since_id)
        events = _filter_events(
            raw_events,
            minimum_level=normalized_level,
            limit=limit,
        )
        return BaseRouteHelper.ok(
            {
                "events": events,
                "next_id": broker.next_id,
            }
        )

    @router.get("/live")
    async def log_live(request: Request, limit: int = 100, min_level: str = "INFO") -> StreamingResponse:
        broker = get_log_broker()
        normalized_level = _normalize_min_level(min_level)
        last_event_id = str(request.headers.get("Last-Event-ID") or "").strip()
        try:
            since_id = int(last_event_id) if last_event_id else 0
        except Exception:
            since_id = 0
        raw_history = broker.history(limit=min(max(int(limit or 100) * 5, 200), 1000), since_id=since_id)
        history = _filter_events(
            raw_history,
            minimum_level=normalized_level,
            limit=limit,
        )
        queue = broker.subscribe()

        async def event_generator():
            try:
                for event in history:
                    yield _format_log_sse(event)
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=12.0)
                        event_dict = event.to_dict()
                        if _level_passes(str(event_dict.get("level", "")), normalized_level):
                            yield _format_log_sse(event_dict)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                broker.unsubscribe(queue)

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=headers,
        )

    return router


__all__ = ["create_log_router"]
