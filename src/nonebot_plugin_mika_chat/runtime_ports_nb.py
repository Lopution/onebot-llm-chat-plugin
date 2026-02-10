"""NoneBot runtime ports bundle.

Adapter registers host bot/event refs for each envelope and exposes
MessagePort + HostEventPort implementations to core engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from mika_chat_core.contracts import ContentPart, EventEnvelope, SendMessageAction
from mika_chat_core.ports.host_events import HostEventPort
from mika_chat_core.ports.message import MessagePort
from mika_chat_core.utils.safe_api import safe_call_api, safe_send


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
class NoneBotRuntimePort(MessagePort, HostEventPort):
    """Shared runtime port for event resolution and message send."""

    _by_message_id: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)
    _by_session_id: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)

    def register_event(self, envelope: EventEnvelope, *, bot: Any, event: Any) -> None:
        message_id = str(envelope.message_id or "").strip()
        session_id = str(envelope.session_id or "").strip()
        if message_id:
            self._by_message_id[message_id] = (bot, event)
        if session_id:
            self._by_session_id[session_id] = (bot, event)

    def resolve_event(self, envelope: EventEnvelope) -> Optional[Tuple[Any, Any]]:
        message_id = str(envelope.message_id or "").strip()
        if message_id and message_id in self._by_message_id:
            return self._by_message_id[message_id]
        session_id = str(envelope.session_id or "").strip()
        if session_id and session_id in self._by_session_id:
            return self._by_session_id[session_id]
        return None

    def _resolve_for_action(self, action: SendMessageAction) -> Optional[Tuple[Any, Any]]:
        reply_to = str(action.reply_to or "").strip()
        if reply_to and reply_to in self._by_message_id:
            return self._by_message_id[reply_to]
        session_id = str(action.session_id or "").strip()
        if session_id and session_id in self._by_session_id:
            return self._by_session_id[session_id]
        return None

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

    async def fetch_message(self, message_id: str) -> Optional[dict[str, Any]]:
        runtime_ref = self._by_message_id.get(str(message_id))
        if runtime_ref is None and self._by_session_id:
            runtime_ref = next(iter(self._by_session_id.values()))
        if runtime_ref is None:
            return None

        bot, _ = runtime_ref
        msg_id_arg: Any = int(message_id) if str(message_id).isdigit() else message_id
        msg_data = await safe_call_api(bot, "get_msg", message_id=msg_id_arg)
        if msg_data is None:
            msg_data = await safe_call_api(bot, "get_message", message_id=msg_id_arg)
        if isinstance(msg_data, dict):
            return msg_data
        return None


@dataclass
class NoneBotPortsBundle:
    message: NoneBotRuntimePort
    host_events: NoneBotRuntimePort

    def register_event(self, envelope: EventEnvelope, *, bot: Any, event: Any) -> None:
        self.host_events.register_event(envelope, bot=bot, event=event)


_runtime_port = NoneBotRuntimePort()
_ports_bundle = NoneBotPortsBundle(message=_runtime_port, host_events=_runtime_port)


def get_runtime_ports_bundle() -> NoneBotPortsBundle:
    return _ports_bundle
