"""tests 专用 NoneBot 轻量 stub（仅在缺少真实 nonebot2 依赖时由 conftest 注入）。

提供本仓库插件与测试所需的最小 API：
- logger
- get_driver / get_plugin_config / get_bot
- on_message / on_command
- get_app (占位)

注意：这是测试 stub，不应被生产路径导入。
"""

from __future__ import annotations

import logging
from typing import Any, Optional


class _StubLogger:
    def __init__(self) -> None:
        self._logger = logging.getLogger("nonebot")

    def debug(self, *args: Any, **kwargs: Any) -> None:
        self._logger.debug(*args, **kwargs)

    def info(self, *args: Any, **kwargs: Any) -> None:
        self._logger.info(*args, **kwargs)

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(*args, **kwargs)

    def error(self, *args: Any, **kwargs: Any) -> None:
        self._logger.error(*args, **kwargs)

    def exception(self, *args: Any, **kwargs: Any) -> None:
        self._logger.exception(*args, **kwargs)

    def success(self, *args: Any, **kwargs: Any) -> None:
        # 项目中大量使用 nonebot.logger.success，这里映射到 info。
        self._logger.info(*args, **kwargs)


logger = _StubLogger()

# conftest 可能会直接写入 nonebot._driver
_driver: Optional[Any] = None


def get_driver() -> Any:
    if _driver is None:
        raise RuntimeError("nonebot stub: driver is not set")
    return _driver


def get_plugin_config(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("nonebot stub: get_plugin_config is not patched")


def get_bot(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("nonebot stub: get_bot is not patched")


class _StubMatcher:
    def handle(self, *args: Any, **kwargs: Any):
        def deco(fn):
            return fn

        return deco


def on_message(*_args: Any, **_kwargs: Any) -> _StubMatcher:
    return _StubMatcher()


def on_command(*_args: Any, **_kwargs: Any) -> _StubMatcher:
    return _StubMatcher()


def get_app(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("nonebot stub: get_app is not available in tests")

