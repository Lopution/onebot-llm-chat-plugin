"""Compatibility bridge for legacy imports.

Do not import adapter modules at module-import time, otherwise importing
`mika_chat_core.handlers` directly can create circular imports through
`nonebot_plugin_mika_chat.__init__`.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .utils.nb_types import BotT, EventT


def _deps_module():
    from nonebot_plugin_mika_chat import deps_nb

    return deps_nb


async def get_chat_history(bot: BotT, event: EventT) -> List[Dict[str, Any]]:
    return await _deps_module().get_chat_history(bot, event)


async def get_user_profile_data(bot: BotT, event: EventT) -> Dict[str, Any]:
    return await _deps_module().get_user_profile_data(bot, event)


async def get_processed_images(bot: BotT, event: EventT) -> List[Dict[str, Any]]:
    return await _deps_module().get_processed_images(bot, event)


def get_gemini_client_dep():
    return _deps_module().get_gemini_client_dep()


def get_config():
    return _deps_module().get_config()


__all__ = [
    "get_chat_history",
    "get_user_profile_data",
    "get_processed_images",
    "get_gemini_client_dep",
    "get_config",
]
