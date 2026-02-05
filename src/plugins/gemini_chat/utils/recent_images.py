"""跨消息图片缓存模块（对外导出入口）。

实现跨消息图片识别功能，允许用户在发送图片后，
通过后续消息 @bot 来请求识别该图片。

功能特性：
- 群级缓存（群聊）和用户级缓存（私聊）
- 可配置的 TTL（默认 5 分钟）
- 消息序列连续性检测（防止跨越太多消息后仍然引用旧图片）
- 关键词检测（判断用户是否在询问图片）
- 图片来源提示

相关模块：
- [`image_cache_core`](image_cache_core.py:1): 缓存核心实现
- [`image_cache_api`](image_cache_api.py:1): 全局单例访问
"""

from typing import Optional

from .image_cache_core import ImageCache
from .image_cache_api import get_image_cache, init_image_cache

__all__ = ["ImageCache", "get_image_cache", "init_image_cache"]
