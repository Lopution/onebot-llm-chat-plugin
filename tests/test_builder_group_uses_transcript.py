from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_builder_group_uses_archive_transcript(temp_database, monkeypatch):
    from mika_chat_core import runtime as runtime_module
    from mika_chat_core.config import Config
    from mika_chat_core.mika_api_layers.core.messages import build_messages
    from mika_chat_core.utils.speaker_labels import speaker_label_for_user_id

    runtime_module.set_config(
        Config(
            llm_api_key="test-api-key-12345678901234567890",
            llm_api_key_list=[],
            llm_base_url="https://test.api.example.com/v1",
            llm_model="mika-test",
            llm_fast_model="mika-test-fast",
            mika_validate_on_startup=False,
            mika_master_id=123456789,
            mika_master_name="TestSensei",
            mika_prompt_file="",
            mika_system_prompt="测试助手",
            mika_bot_display_name="Mika",
            mika_proactive_chatroom_history_lines=3,
            mika_chatroom_transcript_line_max_chars=240,
            mika_reply_private=True,
            mika_reply_at=True,
        )
    )

    # Insert archive rows for group:g1
    await temp_database.execute(
        """
        INSERT INTO message_archive (context_key, user_id, role, content, message_id, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("group:g1", "1", "user", "[Alice(1)]: hello", "m1", 1.0),
    )
    await temp_database.execute(
        """
        INSERT INTO message_archive (context_key, user_id, role, content, message_id, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("group:g1", "bot", "assistant", "ok", "m2", 2.0),
    )
    await temp_database.commit()

    monkeypatch.setattr("mika_chat_core.utils.context_db.get_db", AsyncMock(return_value=temp_database))

    result = await build_messages(
        "new msg",
        user_id="u1",
        group_id="g1",
        image_urls=[],
        search_result="",
        model="mika-test",
        system_prompt="sys",
        available_tools=[],
        system_injection=None,
        context_level=0,
        get_context_async=AsyncMock(return_value=[]),
        enable_tools=False,
        use_persistent=False,
    )

    sys_msgs = [m for m in (result.request_body.get("messages") or []) if m.get("role") == "system"]
    assert any("[Chatroom Transcript]" in str(m.get("content") or "") for m in sys_msgs)
    transcript = next(str(m.get("content") or "") for m in sys_msgs if "[Chatroom Transcript]" in str(m.get("content") or ""))
    assert f"{speaker_label_for_user_id('1')}: hello" in transcript
    assert "Mika: ok" in transcript
