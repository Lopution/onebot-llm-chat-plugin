"""Example external tool plugin."""

from __future__ import annotations

import random
from typing import Any

from mika_chat_core.tools_registry import ToolDefinition


class Plugin:
    name = "dice_roller"
    version = "0.1.0"

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="roll_dice",
                description="Roll an n-sided dice.",
                parameters={
                    "type": "object",
                    "properties": {
                        "sides": {"type": "integer", "minimum": 2, "default": 6},
                    },
                },
                handler=self._roll_dice,
                source="plugin",
            )
        ]

    async def on_load(self) -> None:
        return None

    async def on_unload(self) -> None:
        return None

    async def _roll_dice(self, args: dict[str, Any], group_id: str) -> str:
        del group_id
        sides = int((args or {}).get("sides", 6) or 6)
        sides = max(2, min(sides, 1000))
        return f"掷出了 {random.randint(1, sides)} 点！"
