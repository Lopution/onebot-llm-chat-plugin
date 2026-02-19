"""Compatibility bridge for legacy imports.

核心不直接依赖宿主适配层；由 runtime 注入依赖钩子。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .runtime import get_client as get_runtime_client
from .runtime import get_config as get_runtime_config
from .runtime import get_dep_hook

log = logging.getLogger(__name__)
_warned_missing_hooks: set[str] = set()


def _warn_missing_hook_once(hook_name: str) -> None:
    if hook_name in _warned_missing_hooks:
        return
    _warned_missing_hooks.add(hook_name)
    log.warning(
        "deps compatibility bridge fallback is active for '%s'; "
        "this path is kept for backward compatibility and should be phased out.",
        hook_name,
    )


def _fallback_chat_history(*_args: Any, **_kwargs: Any) -> List[Dict[str, Any]]:
    return []


def _fallback_user_profile(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
    return {}


def _fallback_processed_images(*_args: Any, **_kwargs: Any) -> List[Dict[str, Any]]:
    return []


async def get_chat_history(*args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    """Deprecated compatibility hook.

    仅为外部历史调用兼容保留；核心链路已迁移为 envelope + ports。
    """
    hook = get_dep_hook("get_chat_history")
    if hook is None:
        _warn_missing_hook_once("get_chat_history")
        return _fallback_chat_history(*args, **kwargs)
    return await hook(*args, **kwargs)


async def get_user_profile_data(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Deprecated compatibility hook."""
    hook = get_dep_hook("get_user_profile_data")
    if hook is None:
        _warn_missing_hook_once("get_user_profile_data")
        return _fallback_user_profile(*args, **kwargs)
    return await hook(*args, **kwargs)


async def get_processed_images(*args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    """Deprecated compatibility hook."""
    hook = get_dep_hook("get_processed_images")
    if hook is None:
        _warn_missing_hook_once("get_processed_images")
        return _fallback_processed_images(*args, **kwargs)
    return await hook(*args, **kwargs)


def get_mika_client_dep():
    hook = get_dep_hook("get_mika_client_dep")
    if hook is not None:
        return hook()
    _warn_missing_hook_once("get_mika_client_dep")
    return get_runtime_client()


def get_config():
    hook = get_dep_hook("get_config")
    if hook is not None:
        return hook()
    _warn_missing_hook_once("get_config")
    return get_runtime_config()


__all__ = [
    "get_chat_history",
    "get_user_profile_data",
    "get_processed_images",
    "get_mika_client_dep",
    "get_config",
]
