"""Deprecated — use ``from mika_chat_core.config import Config`` directly.

This shim remains only for third-party code that may still import from here.
It will be removed in a future version.
"""

import warnings as _warnings

_warnings.warn(
    "mika_chat_core.settings is deprecated; import Config from mika_chat_core.config instead.",
    DeprecationWarning,
    stacklevel=2,
)

from .config import Config  # noqa: F401, E402

__all__ = ["Config"]
