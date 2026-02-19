"""请求上下文载荷构建测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope


def _build_envelope(*, is_group: bool) -> EventEnvelope:
    group_id = "123456" if is_group else ""
    session_id = f"group:{group_id}" if is_group else "private:10001"
    return EventEnvelope(
        schema_version=1,
        session_id=session_id,
        platform="test",
        protocol="test",
        message_id="m-1",
        timestamp=0.0,
        author=Author(id="10001", nickname="tester"),
        bot_self_id="bot-1",
        content_parts=[ContentPart(kind="text", text="fallback text")],
        meta={"group_id": group_id, "user_id": "10001", "is_group": is_group, "is_tome": False},
    )


@pytest.mark.asyncio
async def test_build_request_context_payload_group_merges_reply_images():
    from mika_chat_core.handlers import build_request_context_payload_from_envelope

    envelope = _build_envelope(is_group=True)
    plugin_config = SimpleNamespace(
        mika_max_images=5,
        mika_quote_image_caption_enabled=True,
        mika_quote_image_caption_prompt="[引用图片共{count}张]",
        mika_quote_image_caption_timeout_seconds=3.0,
    )

    with patch(
        "mika_chat_core.handlers.parse_envelope_with_mentions",
        new=AsyncMock(return_value=("hello group", ["https://img.example/reply1.jpg"])),
    ), patch(
        "mika_chat_core.handlers._resolve_image_urls_via_port",
        new=AsyncMock(return_value=["https://img.example/main1.jpg"]),
    ):
        payload = await build_request_context_payload_from_envelope(envelope, plugin_config)

    assert payload.message_text == "hello group"
    assert payload.reply_images == ["https://img.example/reply1.jpg"]
    assert payload.image_urls == [
        "https://img.example/main1.jpg",
        "https://img.example/reply1.jpg",
    ]


@pytest.mark.asyncio
async def test_build_request_context_payload_private_uses_plaintext():
    from mika_chat_core.handlers import build_request_context_payload_from_envelope

    envelope = _build_envelope(is_group=False)
    plugin_config = SimpleNamespace(mika_max_images=3)

    with patch(
        "mika_chat_core.handlers._resolve_image_urls_via_port",
        new=AsyncMock(return_value=[]),
    ):
        payload = await build_request_context_payload_from_envelope(envelope, plugin_config)

    assert payload.message_text == "fallback text"
    assert payload.reply_images == []
    assert payload.image_urls == []
