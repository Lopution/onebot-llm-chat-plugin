"""Tool handlers for mika_chat_core.

核心层只提供宿主无关实现；宿主特定能力（如 get_msg）通过 runtime 注入覆盖。

实际工具实现已拆分到 tools_builtin/ 子包；
本文件保留框架（装饰器、注册表、覆盖解析）并作为向后兼容外观。
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from .infra.logging import logger
from .runtime import get_config as get_runtime_config
from .runtime import get_tool_override
from .tools_registry import ToolDefinition, get_tool_registry


TOOL_HANDLERS: Dict[str, Callable] = {}
_registry = get_tool_registry()


def tool(
    name: str,
    *,
    description: str = "",
    parameters: Dict[str, Any] | None = None,
    source: str = "builtin",
    enabled: bool = True,
):
    """工具注册装饰器。"""

    def decorator(func: Callable) -> Callable:
        TOOL_HANDLERS[name] = func
        _registry.register(
            ToolDefinition(
                name=name,
                description=description.strip() or str(getattr(func, "__doc__", "") or "").strip() or name,
                parameters=dict(parameters or {"type": "object", "properties": {}}),
                handler=func,  # type: ignore[arg-type]
                source=source,
                enabled=enabled,
            ),
            replace=True,
        )
        return func

    return decorator


def _resolve_tool_override(name: str) -> Callable | None:
    override = get_tool_override(name)
    return override if callable(override) else None


# --- 触发内建工具注册 & 向后兼容 re-export ---
from .tools_builtin import (  # noqa: E402, F401
    handle_fetch_history_images,
    handle_ingest_knowledge,
    handle_search_group_history,
    handle_search_knowledge,
    handle_web_search,
)

from .utils.search_engine import TIME_SENSITIVE_KEYWORDS  # noqa: E402, F401


def needs_search(message: str) -> bool:
    """兼容旧 tests：基于旧关键词策略判断是否需要外部搜索。"""
    from .utils.search_engine import should_search

    return should_search(message)


def extract_images(message: Any, max_images: int = 10):
    """兼容旧 tests：从消息中提取图片 URL。"""
    from .utils.image_processor import extract_images as _extract

    return _extract(message, max_images=max_images)
