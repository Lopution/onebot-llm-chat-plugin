"""WebUI live chat APIs."""

from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncIterator, Callable, Dict

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..config import Config
from ..core_service import _extract_auth_token, _is_loopback_client, _tokens_match
from ..runtime import get_client as get_runtime_client
from ..runtime import get_config as get_runtime_config
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper


DEFAULT_SESSION_ID = "private:webui_admin"
DEFAULT_USER_ID = "webui_admin"
log = logging.getLogger(__name__)
_ws_query_token_deprecation_warned = False


class LiveChatPayload(BaseModel):
    message: str
    session_id: str = DEFAULT_SESSION_ID
    user_id: str = DEFAULT_USER_ID
    group_id: str = ""


def _resolve_chat_scope(payload: LiveChatPayload) -> tuple[str, str, str | None]:
    session_id = str(payload.session_id or "").strip() or DEFAULT_SESSION_ID
    user_id = str(payload.user_id or "").strip() or DEFAULT_USER_ID
    group_id = str(payload.group_id or "").strip() or None
    if session_id.startswith("group:") and not group_id:
        group_id = session_id.removeprefix("group:").strip() or None
    if session_id.startswith("private:") and user_id == DEFAULT_USER_ID:
        tail = session_id.removeprefix("private:").strip()
        if tail:
            user_id = tail
    return session_id, user_id, group_id


async def _chat_once(payload: LiveChatPayload) -> Dict[str, Any]:
    text = str(payload.message or "").strip()
    if not text:
        raise ValueError("message is required")

    session_id, user_id, group_id = _resolve_chat_scope(payload)
    client = get_runtime_client()
    reply = await client.chat(
        text,
        user_id=user_id,
        group_id=group_id,
        image_urls=[],
        enable_tools=True,
    )
    return {
        "session_id": session_id,
        "user_id": user_id,
        "group_id": group_id or "",
        "reply": str(reply or "").strip(),
    }


async def _chat_stream(payload: LiveChatPayload) -> AsyncIterator[str]:
    text = str(payload.message or "").strip()
    if not text:
        raise ValueError("message is required")

    _session_id, user_id, group_id = _resolve_chat_scope(payload)
    client = get_runtime_client()
    stream_method = getattr(client, "chat_stream", None)
    if callable(stream_method):
        async for chunk in stream_method(
            text,
            user_id=user_id,
            group_id=group_id,
            image_urls=[],
            enable_tools=False,
        ):
            piece = str(chunk or "")
            if piece:
                yield piece
        return

    # 兼容旧 runtime client：无流式能力时回退为单次回复。
    result = await _chat_once(payload)
    reply = str(result.get("reply") or "")
    if reply:
        yield reply


def _is_websocket_authorized(websocket: WebSocket, config: Config) -> bool:
    required_token = str(getattr(config, "mika_webui_token", "") or "").strip()
    provided_token = _extract_auth_token(
        str(websocket.headers.get("authorization", "") or ""),
        str(websocket.headers.get("x-mika-webui-token", "") or ""),
    )
    # Keep query-token fallback for backward compatibility, but prioritize headers.
    query_token = ""
    if not provided_token:
        query_token = str(websocket.query_params.get("token", "") or "").strip()
        provided_token = query_token
    if query_token:
        global _ws_query_token_deprecation_warned
        if not _ws_query_token_deprecation_warned:
            _ws_query_token_deprecation_warned = True
            log.warning("websocket query token 已进入兼容期，请尽快迁移到 header/token ticket 方案。")
    if required_token:
        return _tokens_match(required_token, provided_token)
    client_host = str(websocket.client.host if websocket.client else "").strip()
    return _is_loopback_client(client_host)


def create_live_chat_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(prefix="/live-chat", tags=["mika-webui-live-chat"])

    @router.post("/message", dependencies=[Depends(auth_dependency)])
    async def send_live_chat(payload: LiveChatPayload) -> Dict[str, Any]:
        try:
            return BaseRouteHelper.ok(await _chat_once(payload))
        except ValueError as exc:
            return BaseRouteHelper.error_response(str(exc))
        except Exception as exc:
            return BaseRouteHelper.error_response(str(exc), status_code=500)

    @router.websocket("/ws")
    async def live_chat_ws(websocket: WebSocket) -> None:
        config = settings_getter()
        if not _is_websocket_authorized(websocket, config):
            await websocket.close(code=4401)
            return

        await websocket.accept()
        try:
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict):
                    await websocket.send_json({"type": "error", "message": "payload must be object"})
                    continue
                payload = LiveChatPayload(
                    message=str(message.get("message") or ""),
                    session_id=str(message.get("session_id") or DEFAULT_SESSION_ID),
                    user_id=str(message.get("user_id") or DEFAULT_USER_ID),
                    group_id=str(message.get("group_id") or ""),
                )
                request_id = str(message.get("request_id") or uuid.uuid4().hex[:8])
                stream = bool(message.get("stream", False))
                try:
                    if stream:
                        session_id, user_id, group_id = _resolve_chat_scope(payload)
                        chunks: list[str] = []
                        async for delta in _chat_stream(payload):
                            chunks.append(delta)
                            await websocket.send_json(
                                {
                                    "type": "delta",
                                    "request_id": request_id,
                                    "delta": delta,
                                }
                            )
                        result = {
                            "session_id": session_id,
                            "user_id": user_id,
                            "group_id": group_id or "",
                            "reply": "".join(chunks).strip(),
                        }
                    else:
                        result = await _chat_once(payload)
                except Exception as exc:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "request_id": request_id,
                            "message": str(exc),
                        }
                    )
                    continue
                await websocket.send_json(
                    {
                        "type": "reply",
                        "request_id": request_id,
                        **result,
                    }
                )
        except WebSocketDisconnect:
            return

    return router


__all__ = ["LiveChatPayload", "create_live_chat_router"]
