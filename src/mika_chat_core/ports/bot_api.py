"""Host capability port for adapter-specific bot API access."""

from __future__ import annotations

from typing import Any, Protocol


class BotApiPort(Protocol):
    async def get_msg(self, bot: Any, message_id: int) -> dict:
        ...

    async def call(self, bot: Any, api: str, **kwargs: Any) -> Any:
        ...

