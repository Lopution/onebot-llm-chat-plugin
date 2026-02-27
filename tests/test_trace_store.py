from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_trace_store_append_and_get(temp_database, monkeypatch):
    from mika_chat_core.observability import trace_store as trace_store_module
    from mika_chat_core.observability.trace_store import SQLiteTraceStore

    # Isolate from real contexts.db
    monkeypatch.setattr(trace_store_module, "get_db", AsyncMock(return_value=temp_database))

    store = SQLiteTraceStore()
    await store.append_event(
        request_id="r1",
        session_key="group:1",
        user_id="u1",
        group_id="1",
        event={"type": "context_build", "message_count": 3},
    )

    row = await store.get_trace("r1")
    assert row is not None
    assert row.request_id == "r1"
    assert row.session_key == "group:1"
    assert row.user_id == "u1"
    assert row.group_id == "1"
    assert row.events and row.events[0]["type"] == "context_build"


@pytest.mark.asyncio
async def test_trace_store_list_recent_filters_by_session(temp_database, monkeypatch):
    from mika_chat_core.observability import trace_store as trace_store_module
    from mika_chat_core.observability.trace_store import SQLiteTraceStore

    monkeypatch.setattr(trace_store_module, "get_db", AsyncMock(return_value=temp_database))

    store = SQLiteTraceStore()
    await store.append_event(
        request_id="r-a",
        session_key="group:1",
        user_id="u1",
        group_id="1",
        event={"type": "before_llm"},
    )
    await store.append_event(
        request_id="r-b",
        session_key="group:2",
        user_id="u2",
        group_id="2",
        event={"type": "before_llm"},
    )

    group1 = await store.list_recent(session_key="group:1", limit=10)
    assert {item["request_id"] for item in group1} == {"r-a"}

