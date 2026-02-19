from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_context_store_list_sessions_and_get_stats(
    temp_db_path: Path,
    temp_database,
):
    from mika_chat_core.utils.context_store import SQLiteContextStore

    with patch("mika_chat_core.utils.context_db.DB_PATH", temp_db_path), patch(
        "mika_chat_core.utils.context_store.DB_PATH", temp_db_path
    ), patch("mika_chat_core.utils.context_store.get_db", return_value=temp_database):
        store = SQLiteContextStore()
        await store.add_message(
            "1001",
            "user",
            "[小明(1001)]: 你好",
            group_id="2001",
            message_id="g-1",
            timestamp=1700000001.0,
        )
        await store.add_message(
            "1001",
            "assistant",
            "你好呀",
            group_id="2001",
            message_id="g-2",
            timestamp=1700000002.0,
        )
        await store.add_message(
            "1002",
            "user",
            "私聊消息",
            message_id="p-1",
            timestamp=1700000003.0,
        )

        listing = await store.list_sessions(page=1, page_size=20, query="group:")
        assert listing["total"] == 1
        assert listing["items"][0]["session_key"] == "group:2001"
        assert listing["items"][0]["message_count"] == 2

        stats = await store.get_session_stats("group:2001")
        assert stats["exists"] is True
        assert stats["message_count"] == 2
        assert stats["user_message_count"] == 1
        assert stats["assistant_message_count"] == 1
        assert len(stats["preview"]) == 2
        assert stats["preview"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_context_store_clear_session(
    temp_db_path: Path,
    temp_database,
):
    from mika_chat_core.utils.context_store import SQLiteContextStore

    with patch("mika_chat_core.utils.context_db.DB_PATH", temp_db_path), patch(
        "mika_chat_core.utils.context_store.DB_PATH", temp_db_path
    ), patch("mika_chat_core.utils.context_store.get_db", return_value=temp_database):
        store = SQLiteContextStore()
        await store.add_message(
            "1001",
            "user",
            "待清理消息",
            group_id="2001",
            message_id="g-1",
            timestamp=1700000010.0,
        )

        deleted = await store.clear_session("group:2001")
        assert deleted["contexts"] >= 1
        assert deleted["archive"] >= 1

        listing = await store.list_sessions(page=1, page_size=20, query="group:2001")
        assert listing["total"] == 0

        stats = await store.get_session_stats("group:2001")
        assert stats["exists"] is False
