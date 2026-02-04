# deps.py - NoneBot2 依赖注入模块
"""可复用的依赖项定义"""

from typing import List, Dict, Any, Optional, Union
from nonebot.params import Depends
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

# 类型别名
MessageEvent = Union[GroupMessageEvent, PrivateMessageEvent]


async def get_chat_history(
    event: MessageEvent
) -> List[Dict[str, Any]]:
    """依赖项：获取用户聊天历史"""
    from .utils.context_store import get_context_store
    
    store = get_context_store()
    user_id = str(event.user_id)
    group_id = str(event.group_id) if hasattr(event, 'group_id') and event.group_id else None
    
    return await store.get_context(user_id, group_id)


async def get_user_profile_data(event: MessageEvent) -> Dict[str, Any]:
    """依赖项：获取用户档案"""
    from .utils.user_profile import get_user_profile_store
    
    try:
        store = get_user_profile_store()
        return await store.get_profile(str(event.user_id))
    except Exception:
        return {}


async def get_processed_images(event: MessageEvent) -> List[Dict[str, Any]]:
    """依赖项：获取处理后的图片（Base64 格式）"""
    from .utils.image_processor import extract_images
    from .lifecycle import plugin_config
    
    try:
        from .utils.image_processor import get_image_processor
        
        urls = extract_images(event.original_message, plugin_config.gemini_max_images)
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
