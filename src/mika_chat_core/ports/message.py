"""Message capability port.

Core logic emits host-agnostic actions and relies on this protocol for delivery.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from ..contracts import SendMessageAction


class MessagePort(Protocol):
    async def send_message(self, action: SendMessageAction) -> dict[str, Any]:
        ...

    async def fetch_message(self, message_id: str) -> Optional[dict[str, Any]]:
        ...
