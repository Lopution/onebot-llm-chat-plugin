from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from mika_chat_core.memory.dream_agent import DreamAgent, DreamScheduler


class _FakeDreamTools:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.updated: list[dict] = []

    async def search_topics(self, *, session_key: str, limit: int = 20):
        assert session_key == "group:1"
        assert limit > 0
        return [
            {
                "topic": "Python 学习",
                "summary": "在聊 Python",
                "keywords": ["python", "学习"],
                "key_points": ["装饰器"],
                "participants": ["u1"],
                "timestamp_start": 1.0,
                "timestamp_end": 10.0,
                "source_message_count": 2,
                "updated_at": 20.0,
            },
            {
                "topic": "python学习",
                "summary": "继续聊 Python",
                "keywords": ["函数"],
                "key_points": ["闭包"],
                "participants": ["u2"],
                "timestamp_start": 2.0,
                "timestamp_end": 12.0,
                "source_message_count": 1,
                "updated_at": 18.0,
            },
        ]

    async def delete_topic(self, *, session_key: str, topic: str) -> bool:
        self.deleted.append(f"{session_key}:{topic}")
        return True

    async def update_topic(self, **kwargs):
        self.updated.append(dict(kwargs))
        return 1


@pytest.mark.asyncio
async def test_dream_agent_merge_duplicate_topics(monkeypatch):
    fake_tools = _FakeDreamTools()
    monkeypatch.setattr("mika_chat_core.memory.dream_agent.get_dream_tools", lambda: fake_tools)
    monkeypatch.setattr(
        "mika_chat_core.memory.dream_agent.load_prompt_yaml",
        lambda _name: {
            "min_summary_chars": 12,
            "max_merged_summary_chars": 220,
            "max_keywords": 8,
            "max_key_points": 6,
            "max_participants": 8,
        },
    )
    agent = DreamAgent()
    result = await agent.run_session(session_key="group:1", max_iterations=5)

    assert result["merged"] >= 1
    assert result["deleted"] >= 1
    assert result["updated"] >= 1
    assert fake_tools.deleted
    assert fake_tools.updated


@pytest.mark.asyncio
async def test_dream_scheduler_triggers_after_idle(monkeypatch):
    scheduler = DreamScheduler()
    run_mock = AsyncMock(return_value={"merged": 0, "deleted": 0, "updated": 1})
    scheduler._agent.run_session = run_mock  # type: ignore[attr-defined]
    scheduled_tasks: list[asyncio.Task[None]] = []
    real_create_task = asyncio.create_task

    def _track_task(coro, **kwargs):
        task = real_create_task(coro, **kwargs)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", _track_task)
    monotonic_call_count = 0

    def _fake_monotonic() -> float:
        nonlocal monotonic_call_count
        monotonic_call_count += 1
        if monotonic_call_count == 1:
            return 100.0
        return 170.0

    monkeypatch.setattr(
        "mika_chat_core.memory.dream_agent.time.monotonic",
        _fake_monotonic,
    )

    await scheduler.on_session_activity(
        session_key="group:1",
        enabled=True,
        idle_minutes=1,
        max_iterations=3,
        request_id="r1",
    )
    assert run_mock.await_count == 0
    assert len(scheduled_tasks) == 0

    await scheduler.on_session_activity(
        session_key="group:1",
        enabled=True,
        idle_minutes=1,
        max_iterations=3,
        request_id="r2",
    )
    assert len(scheduled_tasks) == 1
    await asyncio.gather(*scheduled_tasks)
    assert run_mock.await_count == 1
