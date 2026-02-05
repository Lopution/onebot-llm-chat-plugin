"""NoneBot2 依赖注入模块。

定义可复用的依赖项，用于 handler 和 matcher 中获取：
- 聊天历史记录
- 用户档案数据
- 处理后的图片
- Gemini 客户端实例
- 插件配置

这些依赖项可通过 NoneBot2 的 Depends 机制注入。
"""

from typing import Any, Dict, List
from nonebot.params import Depends
from .utils.event_context import build_event_context


async def get_chat_history(
    bot: Any,
    event: Any,
) -> List[Dict[str, Any]]:
    """依赖项：获取用户聊天历史"""
    from .utils.context_store import get_context_store
    
    store = get_context_store()
    ctx = build_event_context(bot, event)
    
    return await store.get_context(ctx.user_id, ctx.group_id)


async def get_user_profile_data(bot: Any, event: Any) -> Dict[str, Any]:
    """依赖项：获取用户档案"""
    from .utils.user_profile import get_user_profile_store
    
    try:
        store = get_user_profile_store()
        ctx = build_event_context(bot, event)
        return await store.get_profile(ctx.user_id)
    except Exception:
        return {}


async def get_processed_images(bot: Any, event: Any) -> List[Dict[str, Any]]:
    """依赖项：获取处理后的图片（Base64 格式）"""
    from .utils.image_processor import resolve_image_urls
    from .lifecycle import plugin_config
    
    try:
        from .utils.image_processor import get_image_processor
        
        urls = await resolve_image_urls(
            bot, getattr(event, "original_message", None), int(plugin_config.gemini_max_images)
        )
        if not urls:
            return []
        
        processor = get_image_processor()
        return await processor.process_images(urls)
    except Exception:
        return []


def get_gemini_client_dep():
    """依赖项：获取 Gemini 客户端"""
    from .lifecycle import get_gemini_client
    return get_gemini_client()


def get_config():
    """依赖项：获取插件配置"""
    from .lifecycle import plugin_config
    return plugin_config
