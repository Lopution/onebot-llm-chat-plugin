from __future__ import annotations

import pytest

from mika_chat_core.infra.log_broker import LogBroker


def test_log_broker_history_respects_limit_and_since_id():
    broker = LogBroker(max_events=10)
    for idx in range(1, 8):
        broker.publish("info", f"event-{idx}")

    history = broker.history(limit=3, since_id=0)
    assert [item["message"] for item in history] == ["event-5", "event-6", "event-7"]

    since_history = broker.history(limit=10, since_id=5)
    assert [item["id"] for item in since_history] == [6, 7]


@pytest.mark.asyncio
async def test_log_broker_subscribe_receives_new_event():
    broker = LogBroker(max_events=10)
    queue = broker.subscribe()
    broker.publish("warning", "hello")
    event = await queue.get()
    assert event.level == "WARNING"
    assert event.message == "hello"
    broker.unsubscribe(queue)
