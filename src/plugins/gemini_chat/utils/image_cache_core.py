"""图片缓存核心实现模块。

提供跨消息图片缓存功能，允许用户在发送图片后通过后续消息引用识别：
- 群级缓存（群聊场景）和用户级缓存（私聊场景）
- 可配置的消息间隔限制（max_gap）
- 关键词检测判断用户是否在询问图片
- LRU 淘汰策略防止内存无限增长

相关模块：
- [`image_cache_api`](image_cache_api.py:1): 全局单例访问接口
- [`history_image_policy`](history_image_policy.py:1): 历史图片注入策略
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..metrics import metrics


@dataclass
class CachedImage:
    """缓存的图片信息"""
    url: str
    sender_id: str
    sender_name: str
    message_id: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class CacheEntry:
    """缓存条目，包含图片和消息计数器"""
    images: List[CachedImage] = field(default_factory=list)
    message_counter: int = 0
    last_image_message_id: str = ""

    def increment_counter(self) -> None:
        self.message_counter += 1

    def reset_counter(self) -> None:
        self.message_counter = 0


class ImageCache:
    """图片缓存管理器"""

    IMAGE_KEYWORDS = [
        "这张图", "这个图", "这图", "这幅图", "这张照片", "这个照片",
        "图片", "图中", "图里", "图上", "图是", "图有",
        "照片", "截图", "表情包", "meme",
        "这是什么", "这是啥", "是什么", "是啥",
        "看看", "看一下", "看下", "帮我看", "帮看",
        "识别", "分析", "解读", "描述", "说说",
        "上面", "里面", "上边", "这里",
    ]

    def __init__(
        self,
        max_gap: int = 10,
        require_keyword: bool = True,
        max_images: int = 10,
        max_entries: int = 200,
        keywords: Optional[List[str]] = None,
    ):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_gap = max_gap
        self._require_keyword = require_keyword
        self._max_images = max_images
        self._max_entries = max_entries
        self._keywords = keywords or self.IMAGE_KEYWORDS

    def _make_key(self, group_id: Optional[str], user_id: str) -> str:
        if group_id:
            return f"group_{group_id}"
        return f"user_{user_id}"

    def _has_image_keyword(self, text: str) -> bool:
        text_lower = text.lower()
        return any(kw in text_lower for kw in self._keywords)

    def cache_images(
        self,
        group_id: Optional[str],
        user_id: str,
        image_urls: List[str],
        sender_name: str,
        message_id: str,
    ) -> int:
        if not image_urls:
            return 0

        cache_key = self._make_key(group_id, user_id)

        if cache_key not in self._cache:
            if len(self._cache) >= self._max_entries:
                oldest_key = next(iter(self._cache.keys()), None)
                if oldest_key is not None:
                    del self._cache[oldest_key]
            self._cache[cache_key] = CacheEntry()

        entry = self._cache[cache_key]
        current_time = time.time()
        for url in image_urls:
            entry.images.append(
                CachedImage(
                    url=url,
                    sender_id=user_id,
                    sender_name=sender_name,
                    message_id=message_id,
                    timestamp=current_time,
                )
            )

        if len(entry.images) > self._max_images:
            entry.images = entry.images[-self._max_images:]

        entry.reset_counter()
        entry.last_image_message_id = message_id

        return len(image_urls)

    def record_message(self, group_id: Optional[str], user_id: str, message_id: str) -> None:
        cache_key = self._make_key(group_id, user_id)
        if cache_key in self._cache:
            entry = self._cache[cache_key]
            if message_id != entry.last_image_message_id:
                entry.increment_counter()

    def get_images_for_message(
        self,
        group_id: Optional[str],
        user_id: str,
        message_text: str,
        message_id: str,
    ) -> Tuple[List[Dict[str, str]], Optional[str]]:
        cache_key = self._make_key(group_id, user_id)
        if cache_key not in self._cache:
            metrics.image_cache_miss_total += 1
            return [], None

        entry = self._cache[cache_key]
        if not entry.images:
            metrics.image_cache_miss_total += 1
            return [], None

        if entry.message_counter > self._max_gap:
            entry.images.clear()
            metrics.image_cache_miss_total += 1
            return [], None

        if self._require_keyword and not self._has_image_keyword(message_text):
            metrics.image_cache_miss_total += 1
            return [], None

        sorted_images = sorted(entry.images, key=lambda x: x.timestamp, reverse=True)
        image_data_list = [
            {"url": img.url, "message_id": img.message_id, "sender_name": img.sender_name}
            for img in sorted_images
        ]

        senders: Dict[str, str] = {}
        for img in sorted_images:
            if img.sender_id not in senders:
                senders[img.sender_id] = img.sender_name

        if len(senders) == 1:
            sender_id, sender_name = list(senders.items())[0]
            if group_id and sender_id != user_id:
                hint = f"[引用了 {sender_name} 发送的 {len(image_data_list)} 张图片]"
            else:
                hint = f"[引用了之前发送的 {len(image_data_list)} 张图片]"
        else:
            hint = f"[引用了 {len(senders)} 位用户发送的共 {len(image_data_list)} 张图片]"

        metrics.image_cache_hit_total += 1
        return image_data_list, hint

    def clear_cache(self, group_id: Optional[str] = None, user_id: Optional[str] = None) -> None:
        if group_id:
            key = f"group_{group_id}"
            if key in self._cache:
                del self._cache[key]
        elif user_id:
            key = f"user_{user_id}"
            if key in self._cache:
                del self._cache[key]
        else:
            self._cache.clear()

    def get_images_by_message_id(
        self,
        group_id: Optional[str],
        user_id: str,
        message_id: str,
    ) -> Tuple[List[CachedImage], bool]:
        cache_key = self._make_key(group_id, user_id)
        if cache_key not in self._cache:
            return [], False

        entry = self._cache[cache_key]
        matched = [img for img in entry.images if img.message_id == message_id]
        return matched, len(matched) > 0

    def peek_recent_images(
        self,
        group_id: Optional[str],
        user_id: str,
        limit: int = 4,
    ) -> List[CachedImage]:
        """只读获取最近图片（不检查关键词，不改变状态）
        
        用于 history image policy 获取候选集，不触发 metrics 更新。
        
        Args:
            group_id: 群组 ID（群聊）或 None（私聊）
            user_id: 用户 ID
            limit: 返回最多几张（默认 4）
            
        Returns:
            最近的 CachedImage 列表（按时间降序）
        """
        cache_key = self._make_key(group_id, user_id)
        if cache_key not in self._cache:
            return []
        
        entry = self._cache[cache_key]
        if not entry.images:
            return []
        
        # 按时间降序排列，取最近 limit 张
        sorted_images = sorted(entry.images, key=lambda x: x.timestamp, reverse=True)
        return sorted_images[:limit]

    def get_stats(self) -> Dict[str, int]:
        total_images = sum(len(entry.images) for entry in self._cache.values())
        return {
            "cache_entries": len(self._cache),
            "total_images": total_images,
            "max_gap": self._max_gap,
            "max_entries": self._max_entries,
        }
