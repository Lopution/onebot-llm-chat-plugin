"""session_lock 单元测试。"""

from __future__ import annotations

import pytest

from mika_chat_core.utils.session_lock import SessionLockManager


def test_get_lock_returns_same_instance_for_same_key():
    manager = SessionLockManager(max_locks=8, ttl_seconds=60)
    lock1 = manager.get_lock("group:1")
    lock2 = manager.get_lock("group:1")
    assert lock1 is lock2


def test_get_lock_uses_default_key_for_empty_input():
    manager = SessionLockManager(max_locks=8, ttl_seconds=60)
    lock1 = manager.get_lock("")
    lock2 = manager.get_lock("   ")
    assert lock1 is lock2


def test_prune_removes_expired_unlocked_locks(monkeypatch):
    from mika_chat_core.utils import session_lock as session_lock_module

    clock = {"now": 100.0}
    monkeypatch.setattr(session_lock_module.time, "monotonic", lambda: clock["now"])

    manager = SessionLockManager(max_locks=8, ttl_seconds=10)
    manager.get_lock("a")
    manager.get_lock("b")

    clock["now"] = 112.0
    manager.get_lock("c")

    assert "a" not in manager._locks
    assert "b" not in manager._locks
    assert "c" in manager._locks


@pytest.mark.asyncio
async def test_prune_keeps_locked_entries(monkeypatch):
    from mika_chat_core.utils import session_lock as session_lock_module

    clock = {"now": 200.0}
    monkeypatch.setattr(session_lock_module.time, "monotonic", lambda: clock["now"])

    manager = SessionLockManager(max_locks=8, ttl_seconds=10)
    lock = manager.get_lock("locked")
    await lock.acquire()
    try:
        clock["now"] = 215.0
        manager.get_lock("new")
        assert "locked" in manager._locks
    finally:
        lock.release()


def test_enforce_limit_removes_oldest_unlocked_lock(monkeypatch):
    from mika_chat_core.utils import session_lock as session_lock_module

    clock = {"now": 300.0}
    monkeypatch.setattr(session_lock_module.time, "monotonic", lambda: clock["now"])

    manager = SessionLockManager(max_locks=2, ttl_seconds=0)
    manager.get_lock("k1")
    clock["now"] += 1
    manager.get_lock("k2")
    clock["now"] += 1
    manager.get_lock("k3")

    assert "k1" not in manager._locks
    assert "k2" in manager._locks
    assert "k3" in manager._locks
