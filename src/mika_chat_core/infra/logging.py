"""Logging abstraction for mika_chat_core.

Core modules should import logger from here instead of importing nonebot
directly. When NoneBot is available, this proxy uses NoneBot's logger.
Otherwise it falls back to stdlib logging.
"""

from __future__ import annotations

import logging
import importlib
from typing import Any


class LoggerProxy:
    def _resolve(self) -> Any:
        try:
            nonebot_module = importlib.import_module("nonebot")
            return getattr(nonebot_module, "logger")
        except Exception:
            return logging.getLogger("mika_chat_core")

    def success(self, message: Any, *args: Any, **kwargs: Any) -> Any:
        resolved = self._resolve()
        if hasattr(resolved, "success"):
            return resolved.success(message, *args, **kwargs)
        return resolved.info(message, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)


logger = LoggerProxy()
log = logger
