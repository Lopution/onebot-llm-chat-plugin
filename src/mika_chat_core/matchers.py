"""Compatibility bridge for legacy imports.

`mika_chat_core.matchers` used to host NoneBot-specific matcher registration.
It now delegates to `nonebot_plugin_mika_chat.matchers`.
"""

from nonebot_plugin_mika_chat import matchers as _nb_matchers
from nonebot_plugin_mika_chat.matchers import *  # noqa: F401,F403


def __getattr__(name: str):
    """Forward legacy/private attribute access to adapter module."""
    return getattr(_nb_matchers, name)
