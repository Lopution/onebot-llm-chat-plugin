"""Core engine facade.

This is intentionally thin for now: host adapters still pass raw event/bot
objects, while future adapters can gradually migrate to `contracts.py`.
"""

from __future__ import annotations

from typing import Any, Optional

from .config import Config
from .handlers import handle_group, handle_private, handle_reset


class ChatEngine:
    async def handle_private(self, bot: Any, event: Any, config: Optional[Config] = None) -> None:
        await handle_private(bot, event, config)

    async def handle_group(
        self, bot: Any, event: Any, config: Optional[Config] = None, *, is_proactive: bool = False
    ) -> None:
        await handle_group(bot, event, config, is_proactive=is_proactive)

    async def handle_reset(self, bot: Any, event: Any, config: Optional[Config] = None) -> None:
        await handle_reset(bot, event, config)

