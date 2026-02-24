"""Logging abstraction for mika_chat_core.

Core modules should import logger from here instead of importing host
framework packages directly. Host adapters may inject a logger via runtime;
otherwise this module falls back to stdlib logging.
"""

from __future__ import annotations

import logging
from typing import Any

from ..runtime import get_config as get_runtime_config, get_logger_port
from .redaction import redact_sensitive_text


class _StdLoggerAdapter:
    def __init__(self) -> None:
        self._logger = logging.getLogger("mika_chat_core")

    def success(self, message: Any, *args: Any, **kwargs: Any) -> Any:
        return self._logger.info(message, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._logger, name)


class LoggerProxy:
    _LOG_CONTROL_KWARGS = {"exc_info", "stack_info", "stacklevel", "extra"}

    def _redaction_enabled(self) -> bool:
        try:
            return bool(getattr(get_runtime_config(), "mika_log_redaction_enabled", True))
        except Exception:
            return True

    def _sanitize_object(self, value: Any) -> Any:
        if not self._redaction_enabled():
            return value
        if isinstance(value, str):
            return redact_sensitive_text(value)
        if isinstance(value, bytes):
            try:
                return redact_sensitive_text(value.decode("utf-8", errors="ignore"))
            except Exception:
                return value
        if isinstance(value, dict):
            return {self._sanitize_object(k): self._sanitize_object(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize_object(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._sanitize_object(item) for item in value)
        return value

    def _render_message(self, message: Any, *args: Any, **kwargs: Any) -> str:
        rendered = str(message)
        if args:
            try:
                rendered = rendered.format(*args)
            except Exception:
                try:
                    rendered = rendered % args
                except Exception:
                    rendered = f"{rendered} | args={args}"
        if kwargs:
            extra_items = {
                key: value
                for key, value in kwargs.items()
                if key not in self._LOG_CONTROL_KWARGS
            }
            if extra_items:
                rendered = f"{rendered} | kwargs={extra_items}"
        if self._redaction_enabled():
            return redact_sensitive_text(rendered)
        return rendered

    def _publish(self, level: str, message: Any, *args: Any, **kwargs: Any) -> None:
        try:
            from .log_broker import get_log_broker

            rendered = self._render_message(message, *args, **kwargs)
            get_log_broker().publish(level, rendered)
        except Exception:
            # 日志分发失败不应影响主流程
            return None

    def _emit(self, level: str, message: Any, *args: Any, **kwargs: Any) -> Any:
        resolved = self._resolve()
        method_name = "info" if level.lower() == "success" else level.lower()
        method = getattr(resolved, method_name, None)
        safe_message = self._sanitize_object(message)
        safe_args = tuple(self._sanitize_object(item) for item in args)
        safe_kwargs = {
            key: (value if key in self._LOG_CONTROL_KWARGS else self._sanitize_object(value))
            for key, value in kwargs.items()
        }
        if callable(method):
            result = method(safe_message, *safe_args, **safe_kwargs)
        else:
            result = resolved.info(safe_message, *safe_args, **safe_kwargs)
        self._publish(level, safe_message, *safe_args, **safe_kwargs)
        return result

    def _resolve(self) -> Any:
        injected = get_logger_port()
        if injected is not None:
            return injected
        return _StdLoggerAdapter()

    def debug(self, message: Any, *args: Any, **kwargs: Any) -> Any:
        return self._emit("debug", message, *args, **kwargs)

    def info(self, message: Any, *args: Any, **kwargs: Any) -> Any:
        return self._emit("info", message, *args, **kwargs)

    def warning(self, message: Any, *args: Any, **kwargs: Any) -> Any:
        return self._emit("warning", message, *args, **kwargs)

    def error(self, message: Any, *args: Any, **kwargs: Any) -> Any:
        return self._emit("error", message, *args, **kwargs)

    def exception(self, message: Any, *args: Any, **kwargs: Any) -> Any:
        return self._emit("exception", message, *args, **kwargs)

    def critical(self, message: Any, *args: Any, **kwargs: Any) -> Any:
        return self._emit("critical", message, *args, **kwargs)

    def success(self, message: Any, *args: Any, **kwargs: Any) -> Any:
        return self._emit("success", message, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)


logger = LoggerProxy()
log = logger
