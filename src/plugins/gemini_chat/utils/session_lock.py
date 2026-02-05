"""会话锁管理模块（LRU + TTL 淘汰）。

解决"按会话/按用户建锁"的常见问题——锁字典无界增长导致内存溢出。

策略：
- 按 key 发放 asyncio.Lock（同一个 key 始终拿到同一把锁）
- LRU 顺序维护 + TTL 淘汰
- 只淘汰"未被占用"的锁，避免影响正在处理的会话

使用场景：
- 用户会话并发控制
- 用户档案抽取任务串行化
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class _LockEntry:
    lock: asyncio.Lock
    last_used: float


class SessionLockManager:
    """会话锁池（LRU + TTL 淘汰）。"""

    def __init__(self, *, max_locks: int = 512, ttl_seconds: float = 3600.0) -> None:
        self._max_locks = max(1, int(max_locks))
        self._ttl_seconds = max(0.0, float(ttl_seconds))
        self._locks: "OrderedDict[str, _LockEntry]" = OrderedDict()

    def get_lock(self, key: str) -> asyncio.Lock:
        k = str(key or "").strip()
        if not k:
            k = "__default__"

        now = time.monotonic()
        self._prune(now)

        entry = self._locks.get(k)
        if entry is not None:
            entry.last_used = now
            self._locks.move_to_end(k)
            return entry.lock

        lock = asyncio.Lock()
        self._locks[k] = _LockEntry(lock=lock, last_used=now)
        self._locks.move_to_end(k)
        self._enforce_limit(now)
        return lock

    def _prune(self, now: float) -> None:
        if self._ttl_seconds <= 0:
            return

        expire_before = now - self._ttl_seconds
        # OrderedDict 按 LRU 顺序（最旧在前）。一旦遇到未过期条目即可提前停止。
        for k, entry in list(self._locks.items()):
            if entry.last_used >= expire_before:
                break
            if entry.lock.locked():
                continue
            self._locks.pop(k, None)

    def _enforce_limit(self, now: float) -> None:
        # 优先淘汰最旧且未被占用的锁。
        while len(self._locks) > self._max_locks:
            k, entry = next(iter(self._locks.items()))
            if entry.lock.locked():
                # 最旧的锁正在使用：剩下的很可能也在用，避免在这里空转。
                break
            self._locks.popitem(last=False)


_default_manager: SessionLockManager | None = None


def get_session_lock_manager() -> SessionLockManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = SessionLockManager()
    return _default_manager
