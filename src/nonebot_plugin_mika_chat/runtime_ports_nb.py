"""NoneBot runtime ports bundle.

Adapter registers host bot/event refs for each envelope and exposes:
- OutboundMessagePort (send/fetch/forward)
- InboundEventPort (event register/resolve)
- PlatformApiPort (history/member/file/message lookups)
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, AsyncIterator, Optional, Tuple

from mika_chat_core.contracts import ContentPart, EventEnvelope, PlatformCapabilities, SendMessageAction, SessionKey
from mika_chat_core.ports.bot_api import PlatformApiPort
from mika_chat_core.ports.host_events import InboundEventPort
from mika_chat_core.ports.message import OutboundMessagePort
from .safe_api import safe_call_api, safe_send

EVENT_INDEX_MAX_ENTRIES = 10000
EVENT_INDEX_TTL_SECONDS = 1800.0


def _to_message_payload(parts: list[ContentPart]) -> Any:
    if not parts:
        return ""

    if len(parts) == 1 and parts[0].kind == "text":
        return parts[0].text

    segments: list[dict[str, Any]] = []
    for part in parts:
        if part.kind == "text":
            segments.append({"type": "text", "data": {"text": part.text}})
        elif part.kind == "image":
            file_ref = part.asset_ref
            if file_ref.startswith("http://") or file_ref.startswith("https://"):
                segments.append({"type": "image", "data": {"url": file_ref}})
            else:
                segments.append({"type": "image", "data": {"file": file_ref}})
        elif part.kind == "mention":
            if part.target_id:
                segments.append({"type": "at", "data": {"qq": part.target_id}})
        elif part.kind == "attachment":
            label = part.text or part.asset_ref or "附件"
            segments.append({"type": "text", "data": {"text": f"[{label}]"}})
    if not segments:
        return ""
    return segments


@dataclass
class NoneBotRuntimePort(OutboundMessagePort, InboundEventPort, PlatformApiPort):
    """Shared runtime port for event resolution and message send."""

    _by_message_id: "OrderedDict[str, Tuple[Any, Any, float]]" = field(default_factory=OrderedDict)
    _by_session_id: "OrderedDict[str, Tuple[Any, Any, float]]" = field(default_factory=OrderedDict)
    _index_lock: RLock = field(default_factory=RLock, repr=False)
    _capabilities: PlatformCapabilities = field(
        default_factory=lambda: PlatformCapabilities(
            supports_reply=True,
            supports_image_send=True,
            supports_image_receive=True,
            supports_mentions=True,
            supports_forward_message=True,
            supports_history_fetch=True,
            supports_member_info=True,
            supports_file_resolve=True,
            supports_message_fetch=True,
            platform_name="onebot",
        )
    )

    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    def _get_single_runtime_ref(self) -> Optional[Tuple[Any, Any, float]]:
        with self._index_lock:
            self._prune_indexes()
            if len(self._by_session_id) == 1:
                return next(iter(self._by_session_id.values()))
        return None

    def _prune_indexes(self) -> None:
        now = time.monotonic()
        cutoff = now - EVENT_INDEX_TTL_SECONDS
        for index in (self._by_message_id, self._by_session_id):
            while len(index) > EVENT_INDEX_MAX_ENTRIES:
                index.popitem(last=False)
            while index:
                _, (_, _, created_at) = next(iter(index.items()))
                if created_at >= cutoff:
                    break
                index.popitem(last=False)

    def register_event(
        self,
        envelope: EventEnvelope,
        *,
        bot: Any = None,
        event: Any = None,
        native_refs: Optional[dict[str, Any]] = None,
    ) -> None:
        if native_refs and (bot is None or event is None):
            bot = native_refs.get("bot")
            event = native_refs.get("event")
        if bot is None or event is None:
            return
        with self._index_lock:
            now = time.monotonic()
            message_id = str(envelope.message_id or "").strip()
            session_id = str(envelope.session_id or "").strip()
            if message_id:
                self._by_message_id.pop(message_id, None)
                self._by_message_id[message_id] = (bot, event, now)
            if session_id:
                self._by_session_id.pop(session_id, None)
                self._by_session_id[session_id] = (bot, event, now)
            self._prune_indexes()

    def resolve_event(self, envelope: EventEnvelope) -> Optional[Tuple[Any, Any]]:
        with self._index_lock:
            self._prune_indexes()
            message_id = str(envelope.message_id or "").strip()
            if message_id and message_id in self._by_message_id:
                self._by_message_id.move_to_end(message_id)
                bot, event, _ = self._by_message_id[message_id]
                return bot, event
            session_id = str(envelope.session_id or "").strip()
            if session_id and session_id in self._by_session_id:
                self._by_session_id.move_to_end(session_id)
                bot, event, _ = self._by_session_id[session_id]
                return bot, event
            return None

    def _resolve_for_action(self, action: SendMessageAction) -> Optional[Tuple[Any, Any]]:
        with self._index_lock:
            self._prune_indexes()
            reply_to = str(action.reply_to or "").strip()
            if reply_to and reply_to in self._by_message_id:
                self._by_message_id.move_to_end(reply_to)
                bot, event, _ = self._by_message_id[reply_to]
                return bot, event
            session_id = str(action.session_id or "").strip()
            if session_id and session_id in self._by_session_id:
                self._by_session_id.move_to_end(session_id)
                bot, event, _ = self._by_session_id[session_id]
                return bot, event
            return None

    def resolve_bot_for_session(self, session_id: str) -> Any | None:
        with self._index_lock:
            self._prune_indexes()
            key = str(session_id or "").strip()
            if not key:
                return None
            runtime_ref = self._by_session_id.get(key)
            if runtime_ref is None:
                return None
            self._by_session_id.move_to_end(key)
            bot, _, _ = runtime_ref
            return bot

    async def send_message(self, action: SendMessageAction) -> dict[str, Any]:
        runtime_ref = self._resolve_for_action(action)
        if runtime_ref is None:
            return {
                "ok": False,
                "error": "event_context_not_found",
                "session_id": action.session_id,
                "reply_to": action.reply_to,
            }

        bot, event = runtime_ref
        payload = _to_message_payload(action.parts)
        if not payload:
            return {"ok": False, "error": "empty_payload", "session_id": action.session_id}

        send_kwargs = {}
        if action.reply_to:
            send_kwargs = {"reply_message": True, "at_sender": False}

        ok = await safe_send(bot, event, payload, **send_kwargs)
        return {
            "ok": bool(ok),
            "session_id": action.session_id,
            "reply_to": action.reply_to,
            "parts": [part.to_dict() for part in action.parts],
        }

    async def send_stream(
        self,
        *,
        session_id: str,
        chunks: AsyncIterator[str],
        reply_to: str = "",
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        runtime_ref = self._resolve_for_action(
            SendMessageAction(type="send_message", session_id=session_id, parts=[], reply_to=reply_to)
        )
        if runtime_ref is None:
            return {
                "ok": False,
                "error": "event_context_not_found",
                "session_id": session_id,
                "reply_to": reply_to,
            }

        bot, event = runtime_ref
        stream_meta = dict(meta or {})
        stream_mode = str(stream_meta.get("stream_mode") or "chunked").strip().lower()
        chunk_chars = max(1, int(stream_meta.get("chunk_chars") or 80))
        chunk_delay_ms = max(0, int(stream_meta.get("chunk_delay_ms") or 0))
        first_reply_to = str(reply_to or "")
        sent_count = 0
        total_chars = 0
        failed_reason = ""

        async def _send_text_piece(text: str) -> bool:
            nonlocal first_reply_to, sent_count, total_chars, failed_reason
            payload = str(text or "")
            if not payload:
                return True
            send_kwargs = {}
            if first_reply_to:
                send_kwargs = {"reply_message": True, "at_sender": False}
            ok = await safe_send(bot, event, payload, **send_kwargs)
            if not ok:
                failed_reason = "send_failed"
                return False
            sent_count += 1
            total_chars += len(payload)
            first_reply_to = ""
            if chunk_delay_ms > 0:
                await asyncio.sleep(chunk_delay_ms / 1000.0)
            return True

        if stream_mode == "final_only":
            merged_parts: list[str] = []
            async for chunk in chunks:
                text = str(chunk or "")
                if text:
                    merged_parts.append(text)
            merged_text = "".join(merged_parts)
            if not merged_text:
                return {"ok": False, "error": "empty_stream", "session_id": session_id}
            ok = await _send_text_piece(merged_text)
            return {
                "ok": bool(ok),
                "error": failed_reason if not ok else "",
                "session_id": session_id,
                "reply_to": reply_to,
                "mode": stream_mode,
                "sent_count": sent_count,
                "total_chars": total_chars,
            }

        buffer = ""
        async for chunk in chunks:
            text = str(chunk or "")
            if not text:
                continue
            buffer += text
            while len(buffer) >= chunk_chars:
                piece = buffer[:chunk_chars]
                buffer = buffer[chunk_chars:]
                if not await _send_text_piece(piece):
                    return {
                        "ok": False,
                        "error": failed_reason or "send_failed",
                        "session_id": session_id,
                        "reply_to": reply_to,
                        "mode": stream_mode,
                        "sent_count": sent_count,
                        "total_chars": total_chars,
                    }

        if buffer and not await _send_text_piece(buffer):
            return {
                "ok": False,
                "error": failed_reason or "send_failed",
                "session_id": session_id,
                "reply_to": reply_to,
                "mode": stream_mode,
                "sent_count": sent_count,
                "total_chars": total_chars,
            }

        if sent_count <= 0:
            return {
                "ok": False,
                "error": "empty_stream",
                "session_id": session_id,
                "reply_to": reply_to,
                "mode": stream_mode,
            }
        return {
            "ok": True,
            "session_id": session_id,
            "reply_to": reply_to,
            "mode": stream_mode,
            "sent_count": sent_count,
            "total_chars": total_chars,
        }

    async def fetch_message(self, message_id: str) -> Optional[dict[str, Any]]:
        with self._index_lock:
            self._prune_indexes()
            runtime_ref = self._by_message_id.get(str(message_id))
        if runtime_ref is None:
            return None

        bot, _, _ = runtime_ref
        msg_id_arg: Any = int(message_id) if str(message_id).isdigit() else message_id
        msg_data = await safe_call_api(bot, "get_msg", message_id=msg_id_arg)
        if msg_data is None:
            msg_data = await safe_call_api(bot, "get_message", message_id=msg_id_arg)
        if isinstance(msg_data, dict):
            return msg_data
        return None

    async def fetch_conversation_history(
        self,
        conversation_id: str,
        limit: int = 20,
    ) -> Optional[list[dict[str, Any]]]:
        key = f"group:{conversation_id}"
        bot = self.resolve_bot_for_session(key)
        if bot is None:
            return None

        group_id_arg: Any = int(conversation_id) if str(conversation_id).isdigit() else conversation_id
        count = max(1, int(limit or 20))
        res = await safe_call_api(
            bot,
            "get_group_msg_history",
            group_id=group_id_arg,
            message_count=count,
        )
        if res is None:
            res = await safe_call_api(
                bot,
                "get_group_msg_history",
                group_id=group_id_arg,
                count=count,
            )
        if res is None:
            return None
        messages = (res.get("messages", []) if isinstance(res, dict) else res) or []
        if not isinstance(messages, list):
            return None
        return [dict(item or {}) for item in messages[:count]]

    async def get_member_info(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Optional[dict[str, Any]]:
        bot = self.resolve_bot_for_session(f"group:{conversation_id}")
        if bot is None:
            return None

        group_id_arg: Any = int(conversation_id) if str(conversation_id).isdigit() else conversation_id
        user_id_arg: Any = int(user_id) if str(user_id).isdigit() else user_id
        data = await safe_call_api(
            bot,
            "get_group_member_info",
            group_id=group_id_arg,
            user_id=user_id_arg,
            no_cache=False,
        )
        if isinstance(data, dict):
            return data
        return None

    async def resolve_file_url(self, file_id: str) -> Optional[str]:
        runtime_ref = self._get_single_runtime_ref()
        bot = runtime_ref[0] if runtime_ref is not None else None
        if bot is None:
            return None
        data = await safe_call_api(bot, "get_file", file_id=file_id)
        if not isinstance(data, dict):
            return None
        url = str(data.get("url") or data.get("download_url") or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return None
        return url

    async def send_forward(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        runtime_ref = None
        with self._index_lock:
            self._prune_indexes()
            key = str(session_id or "").strip()
            if key:
                runtime_ref = self._by_session_id.get(key)
        if runtime_ref is None:
            return {"ok": False, "error": "event_context_not_found", "session_id": session_id}

        bot, _, _ = runtime_ref
        try:
            parsed = SessionKey.parse(str(session_id))
            scope = parsed.scope
            conversation_id = parsed.conversation_id
            user_id = parsed.user_id
            # 兼容旧两段式 session_id（例如 private:12345）
            if scope == "private" and not user_id and conversation_id:
                user_id = conversation_id
        except Exception:
            parts = str(session_id or "").split(":", 1)
            scope = parts[0] if parts else ""
            value = parts[1] if len(parts) == 2 else ""
            conversation_id = value if scope == "group" else ""
            user_id = value if scope == "private" else ""

        if scope in {"group", "guild", "channel"} and conversation_id:
            group_id_arg: Any = int(conversation_id) if str(conversation_id).isdigit() else conversation_id
            ok = (
                await safe_call_api(
                    bot,
                    "send_group_forward_msg",
                    group_id=group_id_arg,
                    messages=messages,
                )
            ) is not None
            return {"ok": ok, "session_id": session_id, "scope": scope}

        if scope == "private" and user_id:
            user_id_arg: Any = int(user_id) if str(user_id).isdigit() else user_id
            ok = (
                await safe_call_api(
                    bot,
                    "send_private_forward_msg",
                    user_id=user_id_arg,
                    messages=messages,
                )
            ) is not None
            return {"ok": ok, "session_id": session_id, "scope": scope}

        return {"ok": False, "error": "unsupported_session_scope", "session_id": session_id, "scope": scope}


@dataclass
class NoneBotPortsBundle:
    message: NoneBotRuntimePort
    host_events: NoneBotRuntimePort
    platform_api: NoneBotRuntimePort

    def register_event(self, envelope: EventEnvelope, *, bot: Any, event: Any) -> None:
        self.host_events.register_event(envelope, bot=bot, event=event)


_runtime_port = NoneBotRuntimePort()
_ports_bundle = NoneBotPortsBundle(
    message=_runtime_port,
    host_events=_runtime_port,
    platform_api=_runtime_port,
)


def get_runtime_ports_bundle() -> NoneBotPortsBundle:
    return _ports_bundle
