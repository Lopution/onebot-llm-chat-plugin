from __future__ import annotations

from collections import OrderedDict
from typing import Any, Optional

from nonebot import logger as log


class LRUCache:
    """LRU (最近最少使用) 缓存实现"""

    def __init__(self, max_size: int):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值，命中时将其移动到末尾（最近使用）"""
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """设置缓存值，超出限制时移除最旧的条目"""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        while len(self._cache) > self._max_size:
            removed_key, _ = self._cache.popitem(last=False)
            log.debug(f"LRU缓存淘汰: {removed_key}")

    def delete(self, key: str) -> None:
        """删除缓存条目"""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()

    def __contains__(self, key: str) -> bool:
        return key in self._cache

    def __len__(self) -> int:
        return len(self._cache)
