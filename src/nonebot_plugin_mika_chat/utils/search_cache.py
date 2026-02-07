"""搜索缓存相关的纯函数实现。

提供搜索结果缓存的操作逻辑（无全局状态）：
- 缓存键生成（MD5 哈希）
- 带 TTL 的缓存读取
- 缓存写入与淘汰

注意：
为了保持向后兼容（尤其是测试用例对 `_search_cache` 的直接 patch），
缓存字典本身仍由 [`search_engine`](search_engine.py:1) 模块持有。
该模块仅提供对字典的操作逻辑，供 `search_engine` 包装调用。
"""

from __future__ import annotations

import hashlib
import time
from typing import Dict, Optional, Tuple


def make_cache_key(query: str) -> str:
    """生成缓存键（对查询进行哈希）。"""

    return hashlib.md5(query.encode("utf-8")).hexdigest()


def get_cached_result(
    cache: Dict[str, Tuple[str, float]],
    *,
    query: str,
    ttl_seconds: int,
    now: Optional[float] = None,
) -> Optional[str]:
    """从缓存中读取结果（过期则删除并返回 None）。"""

    if not query:
        return None

    ts_now = time.time() if now is None else float(now)
    cache_key = make_cache_key(query)

    item = cache.get(cache_key)
    if not item:
        return None

    result, ts = item
    if ts_now - ts < ttl_seconds:
        return result

    # 过期：删除
    try:
        del cache[cache_key]
    except KeyError:
        pass
    return None


def set_cached_result(
    cache: Dict[str, Tuple[str, float]],
    *,
    query: str,
    result: str,
    max_size: int,
    now: Optional[float] = None,
) -> None:
    """写入缓存，并在容量超限时淘汰最旧条目。"""

    if not query:
        return

    ts_now = time.time() if now is None else float(now)

    if len(cache) >= max_size:
        oldest_key = min(cache.keys(), key=lambda k: cache[k][1])
        try:
            del cache[oldest_key]
        except KeyError:
            pass

    cache_key = make_cache_key(query)
    cache[cache_key] = (result, ts_now)

