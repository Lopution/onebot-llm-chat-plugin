import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_snapshot_textifies_images_when_history_multimodal_disabled(
    temp_db_path: Path,
    temp_database,
):
    from mika_chat_core.utils.context_store import SQLiteContextStore

    content = [
        {"type": "text", "text": "这是一张图"},
        {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
    ]

    with patch("mika_chat_core.utils.context_db.DB_PATH", temp_db_path), patch(
        "mika_chat_core.utils.context_store.DB_PATH", temp_db_path
    ), patch("mika_chat_core.utils.context_store.get_db", return_value=temp_database):
        store = SQLiteContextStore(history_store_multimodal=False)
        await store.add_message(
            "u1", "user", content, group_id="g1", message_id="m1", timestamp=1.0
        )

        context = await store.get_context("u1", "g1")
        assert isinstance(context[0]["content"], str)
        assert "[图片]" in context[0]["content"]

        async with temp_database.execute(
            "SELECT messages FROM contexts WHERE context_key = ?",
            ("group:g1",),
        ) as cursor:
            row = await cursor.fetchone()
        snapshot_messages = json.loads(row[0])
        assert isinstance(snapshot_messages[0]["content"], str)
        assert "[图片]" in snapshot_messages[0]["content"]

        async with temp_database.execute(
            "SELECT content FROM message_archive WHERE context_key = ? AND message_id = ?",
            ("group:g1", "m1"),
        ) as cursor:
            archive_row = await cursor.fetchone()
        archived_content = json.loads(archive_row[0])
        assert isinstance(archived_content, list)
        assert any(
            isinstance(part, dict) and part.get("type") == "image_url"
            for part in archived_content
        )


@pytest.mark.asyncio
async def test_snapshot_keeps_multimodal_when_enabled(
    temp_db_path: Path,
    temp_database,
):
    from mika_chat_core.utils.context_store import SQLiteContextStore

    content = [
        {"type": "text", "text": "这是一张图"},
        {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
    ]

    with patch("mika_chat_core.utils.context_db.DB_PATH", temp_db_path), patch(
        "mika_chat_core.utils.context_store.DB_PATH", temp_db_path
    ), patch("mika_chat_core.utils.context_store.get_db", return_value=temp_database):
        store = SQLiteContextStore(history_store_multimodal=True)
        await store.add_message(
            "u1", "user", content, group_id="g1", message_id="m1", timestamp=1.0
        )

        context = await store.get_context("u1", "g1")
        assert isinstance(context[0]["content"], list)
        assert any(
            isinstance(part, dict) and part.get("type") == "image_url"
            for part in context[0]["content"]
        )
