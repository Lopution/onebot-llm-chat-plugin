"""Message capability port.

Core logic emits host-agnostic actions and relies on this protocol for delivery.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional, Protocol, runtime_checkable

from ..contracts import SendMessageAction


class MessagePort(Protocol):
    async def send_message(self, action: SendMessageAction) -> dict[str, Any]:
        ...

    async def fetch_message(self, message_id: str) -> Optional[dict[str, Any]]:
        ...


@runtime_checkable
class StreamMessagePort(MessagePort, Protocol):
    """Optional stream send contract.

    Platforms that do not support incremental delivery can still buffer chunks
    and send once, while exposing a consistent core interface.
    """

    async def send_stream(
        self,
        *,
        session_id: str,
        chunks: AsyncIterator[str],
        reply_to: str = "",
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        ...


@runtime_checkable
class OutboundMessagePort(MessagePort, Protocol):
    """Extended outbound messaging contract.

    Adapters that support merged/forward messages should implement this
    interface. Unsupported adapters can return a structured error payload.
    """

    async def send_forward(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        ...
