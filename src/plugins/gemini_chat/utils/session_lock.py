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
    """A small lock pool with LRU + TTL eviction.

    Purpose:
    - Prevent unbounded growth of per-session/per-user asyncio.Lock dictionaries.
    - Provide stable ordering (same key always returns the same lock while present).
    """

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
        # OrderedDict is in LRU order (oldest first). Stop early once not expired.
        for k, entry in list(self._locks.items()):
            if entry.last_used >= expire_before:
                break
            if entry.lock.locked():
                continue
            self._locks.pop(k, None)

    def _enforce_limit(self, now: float) -> None:
        # Prefer evicting old, unlocked entries.
        while len(self._locks) > self._max_locks:
            k, entry = next(iter(self._locks.items()))
            if entry.lock.locked():
                # All remaining oldest locks are in use; avoid spinning.
                break
            self._locks.popitem(last=False)


_default_manager: SessionLockManager | None = None


def get_session_lock_manager() -> SessionLockManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = SessionLockManager()
    return _default_manager

