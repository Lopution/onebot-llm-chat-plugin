"""In-memory fake ports for host-agnostic core tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..contracts import SendMessageAction


@dataclass
class FakeMessagePort:
    sent_actions: list[SendMessageAction] = field(default_factory=list)
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
class FakePorts:
    message: FakeMessagePort = field(default_factory=FakeMessagePort)
    asset: FakeAssetPort = field(default_factory=FakeAssetPort)
    clock: FakeClockPort = field(default_factory=FakeClockPort)
