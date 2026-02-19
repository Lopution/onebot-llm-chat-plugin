"""发送策略阶段管线测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from mika_chat_core.contracts import Author, EventEnvelope


def _build_envelope(*, session_id: str) -> EventEnvelope:
    group_id = session_id.split(":", 1)[1] if session_id.startswith("group:") else ""
    return EventEnvelope(
        schema_version=1,
        session_id=session_id,
        platform="test",
        protocol="test",
        message_id="m-100",
        timestamp=0.0,
        author=Author(id="u-1", nickname="tester"),
        bot_self_id="bot-1",
        content_parts=[],
        meta={"group_id": group_id, "user_id": "u-1", "is_group": bool(group_id), "is_tome": False},
    )


@pytest.mark.asyncio
async def test_send_policy_short_message_prefers_quote_text():
    from mika_chat_core.handlers import SendStageResult, send_reply_with_policy

    envelope = _build_envelope(session_id="private:10001")
    plugin_config = SimpleNamespace(
        mika_forward_threshold=300,
        mika_long_reply_image_fallback_enabled=True,
    )

    with patch(
        "mika_chat_core.handlers._stage_short_quote_text",
        new=AsyncMock(return_value=SendStageResult(ok=True, method="quote_text")),
    ) as short_stage, patch(
        "mika_chat_core.handlers._stage_long_forward",
        new=AsyncMock(),
    ) as long_stage, patch(
        "mika_chat_core.handlers._stage_render_image",
        new=AsyncMock(),
    ) as image_stage, patch(
        "mika_chat_core.handlers._stage_text_fallback",
        new=AsyncMock(),
    ) as fallback_stage:
        await send_reply_with_policy(
            envelope,
            "短消息",
            is_proactive=False,
            plugin_config=plugin_config,
        )

    short_stage.assert_awaited_once()
    long_stage.assert_not_awaited()
    image_stage.assert_not_awaited()
    fallback_stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_policy_long_message_falls_back_to_text_when_forward_and_image_fail():
    from mika_chat_core.handlers import SendStageResult, send_reply_with_policy

    envelope = _build_envelope(session_id="group:20002")
    plugin_config = SimpleNamespace(
        mika_forward_threshold=10,
        mika_long_reply_image_fallback_enabled=True,
    )

    with patch(
        "mika_chat_core.handlers._stage_long_forward",
        new=AsyncMock(return_value=SendStageResult(ok=False, method="forward", error="forward_failed")),
    ) as long_stage, patch(
        "mika_chat_core.handlers._stage_render_image",
        new=AsyncMock(return_value=SendStageResult(ok=False, method="quote_image", error="render_failed")),
    ) as image_stage, patch(
        "mika_chat_core.handlers._stage_text_fallback",
        new=AsyncMock(return_value=SendStageResult(ok=True, method="quote_text_fallback")),
    ) as fallback_stage:
        await send_reply_with_policy(
            envelope,
            "这是一条足够长的消息，会先走 forward，再走图片和文本兜底",
            is_proactive=True,
            plugin_config=plugin_config,
        )

    long_stage.assert_awaited_once()
    image_stage.assert_awaited_once()
    fallback_stage.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_policy_prefers_split_when_enabled():
    from mika_chat_core.handlers import SendStageResult, send_reply_with_policy

    envelope = _build_envelope(session_id="private:10001")
    plugin_config = SimpleNamespace(
        mika_forward_threshold=300,
        mika_message_split_enabled=True,
        mika_message_split_threshold=10,
        mika_message_split_max_chunks=4,
        mika_long_reply_image_fallback_enabled=True,
    )

    with patch(
        "mika_chat_core.handlers._stage_split_text",
        new=AsyncMock(return_value=SendStageResult(ok=True, method="split_text:2")),
    ) as split_stage, patch(
        "mika_chat_core.handlers._stage_short_quote_text",
        new=AsyncMock(),
    ) as short_stage, patch(
        "mika_chat_core.handlers._stage_long_forward",
        new=AsyncMock(),
    ) as long_stage:
        await send_reply_with_policy(
            envelope,
            "这是一条会触发分段发送的长回复文本。",
            is_proactive=False,
            plugin_config=plugin_config,
        )

    split_stage.assert_awaited_once()
    short_stage.assert_not_awaited()
    long_stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_policy_split_stage_receives_max_chunks():
    from mika_chat_core.handlers import SendStageResult, send_reply_with_policy

    envelope = _build_envelope(session_id="private:10001")
    plugin_config = SimpleNamespace(
        mika_forward_threshold=300,
        mika_message_split_enabled=True,
        mika_message_split_threshold=10,
        mika_message_split_max_chunks=5,
        mika_long_reply_image_fallback_enabled=True,
    )

    with patch(
        "mika_chat_core.handlers._stage_split_text",
        new=AsyncMock(return_value=SendStageResult(ok=True, method="split_text:2")),
    ) as split_stage:
        await send_reply_with_policy(
            envelope,
            "这是一条会触发分段发送的长回复文本。",
            is_proactive=False,
            plugin_config=plugin_config,
        )

    split_stage.assert_awaited_once()
    assert split_stage.await_args.kwargs["split_max_chunks"] == 5


@pytest.mark.asyncio
async def test_stage_split_text_caps_chunks_and_merges_tail():
    from mika_chat_core.handlers_reply import _stage_split_text

    sent_texts: list[str] = []
    sent_reply_to: list[str] = []

    class _Port:
        async def send_message(self, action):
            sent_texts.append(str(action.parts[0].text))
            sent_reply_to.append(str(action.reply_to or ""))
            return {"ok": True}

    result = await _stage_split_text(
        "dummy",
        session_id="group:10001",
        reply_to="m-100",
        split_threshold=10,
        split_max_chunks=3,
        message_port_getter=lambda: _Port(),
        split_message_text_fn=lambda *_args, **_kwargs: ["A", "B", "C", "D"],
    )

    assert result.ok is True
    assert result.method == "split_text:3"
    assert sent_texts == ["A", "B", "CD"]
    assert sent_reply_to == ["m-100", "", ""]


@pytest.mark.asyncio
async def test_send_policy_content_safety_replace_before_send():
    from mika_chat_core.handlers import SendStageResult, send_reply_with_policy

    envelope = _build_envelope(session_id="private:10001")
    plugin_config = SimpleNamespace(
        mika_forward_threshold=300,
        mika_long_reply_image_fallback_enabled=True,
        mika_content_safety_enabled=True,
        mika_content_safety_action="replace",
        mika_content_safety_block_keywords=["危险词"],
        mika_content_safety_replacement="这条回复已被安全重写。",
    )

    with patch(
        "mika_chat_core.handlers._stage_short_quote_text",
        new=AsyncMock(return_value=SendStageResult(ok=True, method="quote_text")),
    ) as short_stage:
        await send_reply_with_policy(
            envelope,
            "这里包含危险词，不应原样发送。",
            is_proactive=False,
            plugin_config=plugin_config,
        )

    short_stage.assert_awaited_once()
    sent_text = short_stage.await_args.args[0]
    assert sent_text == "这条回复已被安全重写。"


@pytest.mark.asyncio
async def test_send_policy_content_safety_drop_skips_all_send_stages():
    from mika_chat_core.handlers import send_reply_with_policy

    envelope = _build_envelope(session_id="group:20002")
    plugin_config = SimpleNamespace(
        mika_forward_threshold=10,
        mika_long_reply_image_fallback_enabled=True,
        mika_content_safety_enabled=True,
        mika_content_safety_action="drop",
        mika_content_safety_block_keywords=["危险词"],
        mika_content_safety_replacement="should-not-send",
    )

    with patch("mika_chat_core.handlers._stage_split_text", new=AsyncMock()) as split_stage, patch(
        "mika_chat_core.handlers._stage_short_quote_text", new=AsyncMock()
    ) as short_stage, patch(
        "mika_chat_core.handlers._stage_long_forward", new=AsyncMock()
    ) as long_stage, patch(
        "mika_chat_core.handlers._stage_render_image", new=AsyncMock()
    ) as image_stage, patch(
        "mika_chat_core.handlers._stage_text_fallback", new=AsyncMock()
    ) as fallback_stage:
        await send_reply_with_policy(
            envelope,
            "危险词",
            is_proactive=False,
            plugin_config=plugin_config,
        )

    split_stage.assert_not_awaited()
    short_stage.assert_not_awaited()
    long_stage.assert_not_awaited()
    image_stage.assert_not_awaited()
    fallback_stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_policy_stream_enabled_prefers_stream_stage():
    from mika_chat_core.handlers import SendStageResult, send_reply_with_policy

    envelope = _build_envelope(session_id="group:20002")
    plugin_config = SimpleNamespace(
        mika_forward_threshold=300,
        mika_reply_stream_enabled=True,
        mika_reply_stream_mode="chunked",
        mika_reply_stream_min_chars=1,
        mika_reply_stream_chunk_chars=10,
        mika_reply_stream_delay_ms=0,
        mika_long_reply_image_fallback_enabled=True,
    )

    with patch(
        "mika_chat_core.handlers._stage_stream_text",
        new=AsyncMock(return_value=SendStageResult(ok=True, method="stream_text:2")),
    ) as stream_stage, patch(
        "mika_chat_core.handlers._stage_short_quote_text",
        new=AsyncMock(),
    ) as short_stage, patch(
        "mika_chat_core.handlers._stage_long_forward",
        new=AsyncMock(),
    ) as long_stage:
        await send_reply_with_policy(
            envelope,
            "abcdef",
            is_proactive=False,
            reply_chunks=["abc", "def"],
            plugin_config=plugin_config,
        )

    stream_stage.assert_awaited_once()
    short_stage.assert_not_awaited()
    long_stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_policy_stream_failure_falls_back_to_short_quote():
    from mika_chat_core.handlers import SendStageResult, send_reply_with_policy

    envelope = _build_envelope(session_id="private:10001")
    plugin_config = SimpleNamespace(
        mika_forward_threshold=300,
        mika_reply_stream_enabled=True,
        mika_reply_stream_mode="chunked",
        mika_reply_stream_min_chars=1,
        mika_reply_stream_chunk_chars=10,
        mika_reply_stream_delay_ms=0,
        mika_long_reply_image_fallback_enabled=True,
    )

    with patch(
        "mika_chat_core.handlers._stage_stream_text",
        new=AsyncMock(return_value=SendStageResult(ok=False, method="stream_text", error="stream_not_supported")),
    ) as stream_stage, patch(
        "mika_chat_core.handlers._stage_short_quote_text",
        new=AsyncMock(return_value=SendStageResult(ok=True, method="quote_text")),
    ) as short_stage:
        await send_reply_with_policy(
            envelope,
            "abcdef",
            is_proactive=False,
            reply_chunks=["abc", "def"],
            plugin_config=plugin_config,
        )

    stream_stage.assert_awaited_once()
    short_stage.assert_awaited_once()
