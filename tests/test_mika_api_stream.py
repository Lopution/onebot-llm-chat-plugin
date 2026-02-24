"""MikaClient 流式接口测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_chat_stream_yields_callback_deltas():
    from mika_chat_core.mika_api import MikaClient

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")

    async def fake_chat(*_args, **kwargs):
        stream_handler = kwargs.get("_stream_handler")
        assert stream_handler is not None
        await stream_handler("A")
        await stream_handler("B")
        return "AB"

    client.chat = fake_chat  # type: ignore[method-assign]
    chunks = [chunk async for chunk in client.chat_stream("hi", user_id="u1")]
    assert chunks == ["A", "B"]


@pytest.mark.asyncio
async def test_chat_stream_emits_final_reply_when_no_delta():
    from mika_chat_core.mika_api import MikaClient

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")

    client.chat = AsyncMock(return_value="final-only")  # type: ignore[method-assign]
    chunks = [chunk async for chunk in client.chat_stream("hi", user_id="u1")]
    assert chunks == ["final-only"]


@pytest.mark.asyncio
async def test_chat_stream_enable_tools_fallback_single_chunk():
    from mika_chat_core.mika_api import MikaClient

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")

    client.chat = AsyncMock(return_value="tool-reply")  # type: ignore[method-assign]
    chunks = [
        chunk
        async for chunk in client.chat_stream(
            "hi",
            user_id="u1",
            enable_tools=True,
        )
    ]
    assert chunks == ["tool-reply"]
    assert client.chat.await_count == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_chat_stream_propagates_error_after_emitting_deltas():
    from mika_chat_core.mika_api_layers.orchestrator.streaming import chat_stream_flow

    async def fake_chat(*_args, **kwargs):
        stream_handler = kwargs.get("_stream_handler")
        assert stream_handler is not None
        await stream_handler("A")
        raise RuntimeError("stream failed")

    chunks = []
    with pytest.raises(RuntimeError, match="stream failed"):
        async for chunk in chat_stream_flow(
            message="hello",
            user_id="u1",
            group_id=None,
            image_urls=None,
            enable_tools=False,
            retry_count=2,
            message_id=None,
            system_injection=None,
            context_level=0,
            history_override=None,
            search_result_override=None,
            chat_caller=fake_chat,
            log_obj=AsyncMock(),
        ):
            chunks.append(chunk)
    assert chunks == ["A"]
