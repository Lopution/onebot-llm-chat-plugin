"""Platform API capability port.

This is a host-agnostic contract for adapter-specific upstream APIs
(history/member lookup/file resolve/message lookup). Core should call this
contract instead of directly calling platform-native APIs.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from ..contracts import PlatformCapabilities


@runtime_checkable
class PlatformApiPort(Protocol):
    def capabilities(self) -> PlatformCapabilities:
        """Declare adapter-supported capabilities."""
        ...

    async def fetch_conversation_history(
        self,
        conversation_id: str,
        limit: int = 20,
    ) -> Optional[list[dict[str, Any]]]:
        """Fetch recent conversation history; return None if unsupported."""
        ...

    async def get_member_info(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Optional[dict[str, Any]]:
        """Fetch member profile; return None if unsupported."""
        ...

    async def fetch_message(self, message_id: str) -> Optional[dict[str, Any]]:
        """Fetch message by message id; return None if unsupported."""
        ...

    async def resolve_file_url(self, file_id: str) -> Optional[str]:
        """Resolve platform file id to URL; return None if unsupported."""
        ...
