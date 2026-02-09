"""Compatibility bridge for legacy imports.

核心不直接依赖宿主适配层；由 runtime 注入依赖钩子。
"""

from __future__ import annotations

from typing import Any, Dict, List

from .utils.nb_types import BotT, EventT
from .runtime import get_client as get_runtime_client
from .runtime import get_config as get_runtime_config
from .runtime import get_dep_hook


def _fallback_chat_history(_bot: BotT, _event: EventT) -> List[Dict[str, Any]]:
    return []


def _fallback_user_profile(_bot: BotT, _event: EventT) -> Dict[str, Any]:
    return {}


def _fallback_processed_images(_bot: BotT, _event: EventT) -> List[Dict[str, Any]]:
    return []


async def get_chat_history(bot: BotT, event: EventT) -> List[Dict[str, Any]]:
    hook = get_dep_hook("get_chat_history")
    if hook is None:
        return _fallback_chat_history(bot, event)
    return await hook(bot, event)


async def get_user_profile_data(bot: BotT, event: EventT) -> Dict[str, Any]:
    hook = get_dep_hook("get_user_profile_data")
    if hook is None:
        return _fallback_user_profile(bot, event)
    return await hook(bot, event)


async def get_processed_images(bot: BotT, event: EventT) -> List[Dict[str, Any]]:
    hook = get_dep_hook("get_processed_images")
    if hook is None:
        return _fallback_processed_images(bot, event)
    return await hook(bot, event)


def get_gemini_client_dep():
    hook = get_dep_hook("get_gemini_client_dep")
    if hook is not None:
        return hook()
    return get_runtime_client()


def get_config():
    hook = get_dep_hook("get_config")
    if hook is not None:
        return hook()
    return get_runtime_config()


__all__ = [
    "get_chat_history",
    "get_user_profile_data",
    "get_processed_images",
    "get_gemini_client_dep",
    "get_config",
]
