"""工具处理器模块。

定义和注册 Gemini API Tool Calling 的工具处理器，包括：
- 工具注册装饰器
- web_search 网络搜索工具
- search_group_history 群聊历史搜索工具
- fetch_history_images 历史图片获取工具

使用示例：
    @tool("my_tool")
    async def handle_my_tool(args: dict, group_id: str = "") -> str:
        return "工具执行结果"
"""

from typing import Any, Callable, Dict

from .infra.logging import logger


# 工具注册表
TOOL_HANDLERS: Dict[str, Callable] = {}


def tool(name: str):
    """工具注册装饰器
    
    使用方法:
        @tool("web_search")
        async def web_search_handler(args: dict, group_id: str = "") -> str:
            ...
    
    Args:
        name: 工具名称，用于在 TOOL_HANDLERS 中注册
        
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        TOOL_HANDLERS[name] = func
        return func
    return decorator


@tool("search_group_history")
async def handle_search_group_history(args: dict, group_id: str) -> str:
    """NoneBot 适配层委托实现。"""
    from nonebot_plugin_mika_chat.tools_nb import handle_search_group_history as _impl

    return await _impl(args, group_id)


@tool("web_search")
async def handle_web_search(args: dict, group_id: str = "") -> str:
    """Web 搜索工具处理器
    
    Args:
        args: 工具参数字典，包含 query 参数
        group_id: 群组 ID（未使用）
        
    Returns:
        搜索结果字符串
    """
    from .utils.search_engine import google_search
    
    query = args.get("query", "") if isinstance(args, dict) else str(args)
    logger.debug(f"执行 web_search | query={query}")
    result = await google_search(query, "", "")
    return result if result else "未找到相关搜索结果"


@tool("fetch_history_images")
async def handle_fetch_history_images(args: dict, group_id: str = "") -> str:
    """NoneBot 适配层委托实现。"""
    from nonebot_plugin_mika_chat.tools_nb import handle_fetch_history_images as _impl

    return await _impl(args, group_id)


# extract_images 已移动到 utils.image_processor
# needs_search 和相关常量已废弃，使用 utils.search_engine.should_search


# ==================== 兼容旧 tests 的导出 ====================

# 旧 tests 仍从 gemini_chat.tools 导入这些符号。

from .utils.search_engine import TIME_SENSITIVE_KEYWORDS  # noqa: E402


def needs_search(message: str) -> bool:
    """兼容旧 tests：基于旧关键词策略判断是否需要外部搜索。

    说明：当前推荐使用 [`should_search()`](mika_chat_core/utils/search_engine.py:1)。
    """
    from .utils.search_engine import should_search

    return should_search(message)


def extract_images(message: Any, max_images: int = 10):
    """兼容旧 tests：从消息中提取图片 URL。

    实现委派到 [`utils.image_processor.extract_images()`](mika_chat_core/utils/image_processor.py:1)。
    """
    from .utils.image_processor import extract_images as _extract

    return _extract(message, max_images=max_images)
