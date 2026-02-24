"""NoneBot2 依赖注入模块。

定义可复用的依赖项，用于 handler 和 matcher 中获取：
- 聊天历史记录
- 用户档案数据
- 处理后的图片
- API 客户端实例
- 插件配置

这些依赖项可通过 NoneBot2 的 Depends 机制注入。
"""

from typing import Any, Dict, List
from nonebot.params import Depends
from nonebot import get_plugin_config as nb_get_plugin_config
from nonebot.adapters import Bot, Event

from mika_chat_core.runtime import (
    get_config as get_runtime_config,
    get_platform_api_port as get_runtime_platform_api_port,
)
from mika_chat_core.config import Config
from mika_chat_core.utils.event_context import build_event_context


async def get_chat_history(
    bot: Bot,
    event: Event,
) -> List[Dict[str, Any]]:
    """依赖项：获取用户聊天历史"""
    from mika_chat_core.utils.context_store import get_context_store
    
    store = get_context_store()
    ctx = build_event_context(bot, event)
    
    return await store.get_context(ctx.user_id, ctx.group_id)


async def get_user_profile_data(bot: Bot, event: Event) -> Dict[str, Any]:
    """依赖项：获取用户档案"""
    from mika_chat_core.utils.user_profile import get_user_profile_store
    
    try:
        store = get_user_profile_store()
        ctx = build_event_context(bot, event)
        return await store.get_profile(ctx.user_id)
    except Exception:
        return {}


async def get_processed_images(bot: Bot, event: Event) -> List[Dict[str, Any]]:
    """依赖项：获取处理后的图片（Base64 格式）"""
    from mika_chat_core.utils.image_processor import resolve_image_urls
    
    try:
        from mika_chat_core.utils.image_processor import get_image_processor

        try:
            config = get_runtime_config()
        except Exception:
            config = nb_get_plugin_config(Config)
        urls = await resolve_image_urls(
            getattr(event, "original_message", None),
            int(config.mika_max_images),
            platform_api=get_runtime_platform_api_port(),
        )
        if not urls:
            return []
        
        processor = get_image_processor()
        return await processor.process_images(urls)
    except Exception:
        return []


def get_mika_client_dep():
    """依赖项：获取 API 客户端"""
    from nonebot_plugin_mika_chat.lifecycle_nb import get_mika_client
    return get_mika_client()


def get_config():
    """依赖项：获取插件配置"""
    try:
        return get_runtime_config()
    except Exception:
        return nb_get_plugin_config(Config)
