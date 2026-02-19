"""Core engine facade.

Host-agnostic entrypoint for adapters: `EventEnvelope -> Action[]`.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .contracts import ChatMessage, ChatSession, ContentPart, EventEnvelope, NoopAction, SendMessageAction
from .ports.host_events import HostEventPort
from .ports.message import MessagePort


CoreAction = SendMessageAction | NoopAction
log = logging.getLogger(__name__)


class ChatEngine:
    @staticmethod
    def _resolve_message_port(ports: Any) -> Optional[MessagePort]:
        """Best-effort resolve a message port from ports bundle or direct port."""
        if ports is None:
            return None
        if hasattr(ports, "send_message"):
            return ports  # type: ignore[return-value]
        candidate = getattr(ports, "message", None)
        if candidate is not None and hasattr(candidate, "send_message"):
            return candidate  # type: ignore[return-value]
        return None

    @staticmethod
    def _resolve_host_event_port(ports: Any) -> Optional[HostEventPort]:
        """Best-effort resolve host event port from ports bundle or direct port."""
        if ports is None:
            return None
        if hasattr(ports, "resolve_event"):
            return ports  # type: ignore[return-value]
        candidate = getattr(ports, "host_events", None)
        if candidate is not None and hasattr(candidate, "resolve_event"):
            return candidate  # type: ignore[return-value]
        return None

    @staticmethod
    def _resolve_intent(envelope: EventEnvelope) -> str:
        intent = str(envelope.meta.get("intent") or "").strip().lower()
        if intent:
            return intent
        session_id = str(envelope.session_id or "").strip().lower()
        if session_id.startswith("group:"):
            return "group"
        if session_id.startswith("private:"):
            return "private"
        if envelope.meta.get("group_id"):
            return "group"
        return "private"

    @staticmethod
    def envelope_to_chat_session(envelope: EventEnvelope) -> ChatSession:
        """Bridge envelope into session context model."""
        group_id = envelope.meta.get("group_id") or None
        return ChatSession(
            user_id=str(envelope.author.id or envelope.meta.get("user_id", "")),
            group_id=str(group_id) if group_id else None,
            is_private=not str(envelope.session_id or "").startswith("group:"),
        )

    @staticmethod
    def envelope_to_chat_message(envelope: EventEnvelope) -> ChatMessage:
        """Bridge envelope into internal chat message model."""
        text_chunks: list[str] = []
        mentions: list[str] = []
        images: list[str] = []

        for part in envelope.content_parts:
            if part.kind == "text" and part.text:
                text_chunks.append(part.text)
            elif part.kind == "mention":
                if part.target_id:
                    mentions.append(part.target_id)
                if part.text:
                    text_chunks.append(part.text)
            elif part.kind == "reply" and part.target_id:
                text_chunks.append(f"[reply:{part.target_id}]")
            elif part.kind == "image":
                images.append(part.asset_ref)
                text_chunks.append("[图片]")
            elif part.kind == "attachment":
                text_chunks.append("[附件]")

        return ChatMessage(
            role="user",
            text=" ".join(chunk for chunk in text_chunks if chunk).strip(),
            user_id=str(envelope.author.id or envelope.meta.get("user_id", "")),
            group_id=str(envelope.meta.get("group_id", "")),
            message_id=str(envelope.message_id or ""),
            mentions=mentions,
            images=[img for img in images if img],
            raw={"session_id": envelope.session_id, "platform": envelope.platform, "protocol": envelope.protocol},
        )

    @staticmethod
    def envelope_to_actions(
        envelope: EventEnvelope,
        *,
        reply_text: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> list[CoreAction]:
        """Build host-agnostic actions from an envelope.

        This method is intentionally minimal and side-effect free:
        adapter layers can use it to validate envelope/action closure before
        wiring host-specific APIs.
        """

        text = (reply_text or "").strip()
        if not text:
            text = ChatEngine.envelope_to_chat_message(envelope).text.strip()

        if not text:
            return [
                NoopAction(
                    type="noop",
                    reason="empty_input",
                    meta={"session_id": envelope.session_id, "message_id": envelope.message_id},
                )
            ]

        return [
            SendMessageAction(
                type="send_message",
                session_id=envelope.session_id,
                parts=[ContentPart(kind="text", text=text)],
                reply_to=reply_to if reply_to is not None else envelope.message_id,
            )
        ]

    @staticmethod
    async def dispatch_actions(actions: list[CoreAction], message_port: MessagePort) -> list[dict[str, Any]]:
        """Execute host-agnostic actions through a message port."""

        results: list[dict[str, Any]] = []
        for action in actions:
            if isinstance(action, SendMessageAction):
                result = await message_port.send_message(action)
                results.append(result)
        return results

    @staticmethod
    async def _try_handle_with_host_runtime(
        envelope: EventEnvelope,
        *,
        host_event_port: HostEventPort,
        settings: Optional[Any],
    ) -> Optional[list[CoreAction]]:
        runtime_ref = host_event_port.resolve_event(envelope)
        if runtime_ref is None:
            return None

        intent = ChatEngine._resolve_intent(envelope)
        if intent not in {"reset", "private", "group"}:
            return [
                NoopAction(
                    type="noop",
                    reason="unsupported_intent",
                    meta={"intent": intent, "session_id": envelope.session_id},
                )
            ]

        from .handlers import handle_group, handle_private, handle_reset
        from .runtime import get_client as get_runtime_client
        from .runtime import get_config as get_runtime_config

        plugin_config = settings or get_runtime_config()
        mika_client = get_runtime_client()

        if intent == "reset":
            await handle_reset(
                envelope,
                plugin_config=plugin_config,
                mika_client=mika_client,
            )
        elif intent == "private":
            await handle_private(
                envelope,
                plugin_config=plugin_config,
                mika_client=mika_client,
            )
        else:
            await handle_group(
                envelope,
                plugin_config=plugin_config,
                mika_client=mika_client,
                is_proactive=bool(envelope.meta.get("is_proactive", False)),
                proactive_reason=(
                    str(envelope.meta.get("proactive_reason"))
                    if envelope.meta.get("proactive_reason") is not None
                    else None
                ),
            )

        return [
            NoopAction(
                type="noop",
                reason="handled_by_host_runtime",
                meta={"intent": intent, "session_id": envelope.session_id},
            )
        ]

    @staticmethod
    async def handle_event(
        envelope: EventEnvelope,
        ports: Any,
        settings: Optional[Any] = None,
        *,
        reply_text: Optional[str] = None,
        dispatch: bool = False,
    ) -> list[CoreAction]:
        """Core host-agnostic entrypoint.

        - Input: host-normalized `EventEnvelope`
        - Output: host-agnostic actions
        - Optional side effect: dispatch actions when `dispatch=True`
        """
        host_event_port = ChatEngine._resolve_host_event_port(ports)
        if host_event_port is not None:
            runtime_actions = await ChatEngine._try_handle_with_host_runtime(
                envelope,
                host_event_port=host_event_port,
                settings=settings,
            )
            if runtime_actions is not None:
                if dispatch:
                    message_port = ChatEngine._resolve_message_port(ports)
                    send_actions = [action for action in runtime_actions if isinstance(action, SendMessageAction)]
                    if send_actions and message_port is None:
                        raise ValueError("dispatch requires message port in ports bundle")
                    if send_actions and message_port is not None:
                        await ChatEngine.dispatch_actions(runtime_actions, message_port)
                return runtime_actions

        explicit_intent = str(envelope.meta.get("intent") or "").strip()
        if explicit_intent:
            intent = ChatEngine._resolve_intent(envelope)
            log.warning(
                "host runtime event not found for explicit intent, skip fallback text action | "
                "intent=%s session=%s message=%s",
                intent,
                envelope.session_id,
                envelope.message_id,
            )
            return [
                NoopAction(
                    type="noop",
                    reason="host_runtime_unavailable",
                    meta={"intent": intent, "session_id": envelope.session_id},
                )
            ]

        actions = ChatEngine.envelope_to_actions(envelope, reply_text=reply_text)
        if not dispatch:
            return actions

        message_port = ChatEngine._resolve_message_port(ports)
        if message_port is None:
            raise ValueError("dispatch requires message port in ports bundle")

        await ChatEngine.dispatch_actions(actions, message_port)
        return actions
