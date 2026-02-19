"""In-memory fake ports for host-agnostic core tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from ..contracts import PlatformCapabilities, SendMessageAction


@dataclass
class FakeMessagePort:
    sent_actions: list[SendMessageAction] = field(default_factory=list)
    streamed_texts: list[str] = field(default_factory=list)
    messages: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def send_message(self, action: SendMessageAction) -> dict[str, Any]:
        self.sent_actions.append(action)
        message_id = f"fake-{len(self.sent_actions)}"
        payload = {
            "message_id": message_id,
            "session_id": action.session_id,
            "parts": [part.to_dict() for part in action.parts],
            "reply_to": action.reply_to,
            "mentions": list(action.mentions),
        }
        self.messages[message_id] = payload
        return payload

    async def fetch_message(self, message_id: str) -> Optional[dict[str, Any]]:
        return self.messages.get(message_id)

    async def send_stream(
        self,
        *,
        session_id: str,
        chunks: AsyncIterator[str],
        reply_to: str = "",
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        collected: list[str] = []
        async for chunk in chunks:
            text = str(chunk or "")
            if not text:
                continue
            collected.append(text)
        merged = "".join(collected)
        self.streamed_texts.append(merged)
        payload = {
            "ok": True,
            "session_id": session_id,
            "reply_to": reply_to,
            "text": merged,
            "meta": dict(meta or {}),
            "chunks": len(collected),
        }
        return payload


@dataclass
class FakeOutboundMessagePort(FakeMessagePort):
    forwarded_messages: list[dict[str, Any]] = field(default_factory=list)

    async def send_forward(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "ok": True,
            "session_id": session_id,
            "messages": [dict(item or {}) for item in messages],
            "count": len(messages),
        }
        self.forwarded_messages.append(payload)
        return payload


@dataclass
class FakeAssetPort:
    assets: dict[str, bytes] = field(default_factory=dict)

    async def download(self, asset_ref: str) -> bytes:
        if asset_ref not in self.assets:
            raise KeyError(f"asset not found: {asset_ref}")
        return self.assets[asset_ref]


@dataclass
class FakeClockPort:
    wall_time: float = 0.0
    monotonic_time: float = 0.0

    def now(self) -> float:
        return self.wall_time

    def monotonic(self) -> float:
        return self.monotonic_time

    def tick(self, seconds: float) -> None:
        self.wall_time += seconds
        self.monotonic_time += seconds


@dataclass
class FakePlatformApiPort:
    _capabilities: PlatformCapabilities = field(default_factory=PlatformCapabilities)
    _history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _members: dict[str, dict[str, Any]] = field(default_factory=dict)
    _messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    _file_urls: dict[str, str] = field(default_factory=dict)

    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    async def fetch_conversation_history(
        self,
        conversation_id: str,
        limit: int = 20,
    ) -> Optional[list[dict[str, Any]]]:
        records = self._history.get(conversation_id)
        if records is None:
            return None
        return [dict(item or {}) for item in records[: max(limit, 0)]]

    async def get_member_info(self, conversation_id: str, user_id: str) -> Optional[dict[str, Any]]:
        return self._members.get(f"{conversation_id}:{user_id}")

    async def fetch_message(self, message_id: str) -> Optional[dict[str, Any]]:
        return self._messages.get(message_id)

    async def resolve_file_url(self, file_id: str) -> Optional[str]:
        return self._file_urls.get(file_id)


@dataclass
class FakePorts:
    message: FakeMessagePort = field(default_factory=FakeMessagePort)
    asset: FakeAssetPort = field(default_factory=FakeAssetPort)
    clock: FakeClockPort = field(default_factory=FakeClockPort)
    platform_api: FakePlatformApiPort = field(default_factory=FakePlatformApiPort)
