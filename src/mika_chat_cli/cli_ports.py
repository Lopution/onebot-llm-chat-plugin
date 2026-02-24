"""CLI runtime port implementations.

用于验证 mika_chat_core 在非 NoneBot 宿主中的可运行性。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from mika_chat_core.contracts import PlatformCapabilities, SendMessageAction
from mika_chat_core.ports.bot_api import PlatformApiPort
from mika_chat_core.ports.message import OutboundMessagePort


@dataclass
class CliRuntimePorts(OutboundMessagePort, PlatformApiPort):
    """CLI 模式下的最小端口实现。"""

    output: Callable[[str], None] = print
    _messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    _capabilities: PlatformCapabilities = field(
        default_factory=lambda: PlatformCapabilities(
            supports_reply=False,
            supports_image_send=False,
            supports_image_receive=False,
            supports_mentions=False,
            supports_forward_message=False,
            supports_history_fetch=False,
            supports_member_info=False,
            supports_file_resolve=False,
            supports_message_fetch=True,
            platform_name="cli",
        )
    )

    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    async def send_message(self, action: SendMessageAction) -> dict[str, Any]:
        message_id = str(action.meta.get("message_id") or uuid.uuid4().hex[:8])
        rendered: list[str] = []
        for part in action.parts:
            if part.kind == "text":
                text = str(part.text or "").strip()
                if text:
                    rendered.append(text)
            elif part.kind == "image":
                rendered.append(f"[图片: {str(part.asset_ref or '')[:80]}]")
            elif part.kind == "mention":
                rendered.append(f"@{part.target_id or '用户'}")
            elif part.kind == "attachment":
                rendered.append(f"[附件: {part.text or part.asset_ref or 'attachment'}]")

        payload = "\n".join(rendered).strip() or "[空消息]"
        self.output(f"\n[Mika]: {payload}")
        self._messages[message_id] = {
            "message_id": message_id,
            "session_id": action.session_id,
            "reply_to": action.reply_to,
            "content": payload,
        }
        return {"ok": True, "message_id": message_id, "session_id": action.session_id}

    async def send_forward(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self.output("\n[Mika][Forward]:")
        for msg in messages:
            data = msg.get("data", {}) if isinstance(msg, dict) else {}
            content = str(data.get("content") or "").strip()
            if content:
                self.output(f"  > {content}")
        return {"ok": True, "session_id": session_id}

    async def fetch_message(self, message_id: str) -> Optional[dict[str, Any]]:
        return self._messages.get(str(message_id))

    async def fetch_conversation_history(
        self,
        conversation_id: str,
        limit: int = 20,
    ) -> Optional[list[dict[str, Any]]]:
        return None

    async def get_member_info(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Optional[dict[str, Any]]:
        return None

    async def resolve_file_url(self, file_id: str) -> Optional[str]:
        return None
