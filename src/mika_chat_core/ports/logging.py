"""Logging port abstraction for host adapters."""

from __future__ import annotations

from typing import Any, Protocol


class LoggerPort(Protocol):
    """Minimal logger surface used by mika_chat_core."""

    def debug(self, message: Any, *args: Any, **kwargs: Any) -> Any: ...

    def info(self, message: Any, *args: Any, **kwargs: Any) -> Any: ...

    def warning(self, message: Any, *args: Any, **kwargs: Any) -> Any: ...

    def error(self, message: Any, *args: Any, **kwargs: Any) -> Any: ...

    def exception(self, message: Any, *args: Any, **kwargs: Any) -> Any: ...

    def success(self, message: Any, *args: Any, **kwargs: Any) -> Any: ...
