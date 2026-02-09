"""Logging abstraction for mika_chat_core.

Core modules should import logger from here instead of importing host
framework packages directly. Host adapters may inject a logger via runtime;
otherwise this module falls back to stdlib logging.
"""

from __future__ import annotations

import logging
from typing import Any

from ..runtime import get_logger_port


class _StdLoggerAdapter:
    def __init__(self) -> None:
        self._logger = logging.getLogger("mika_chat_core")

    def success(self, message: Any, *args: Any, **kwargs: Any) -> Any:
        return self._logger.info(message, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._logger, name)


class LoggerProxy:
    def _resolve(self) -> Any:
        injected = get_logger_port()
        if injected is not None:
            return injected
        return _StdLoggerAdapter()

    def success(self, message: Any, *args: Any, **kwargs: Any) -> Any:
        resolved = self._resolve()
        if hasattr(resolved, "success"):
            return resolved.success(message, *args, **kwargs)
        return resolved.info(message, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)


logger = LoggerProxy()
log = logger
