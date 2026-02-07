"""请求上下文载荷构建测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_build_request_context_payload_group_merges_reply_images():
    from gemini_chat.handlers import build_request_context_payload

    bot = MagicMock()
    event = MagicMock()
    event.original_message = []

    plugin_config = SimpleNamespace(
        gemini_max_images=5,
        gemini_quote_image_caption_enabled=True,
        gemini_quote_image_caption_prompt="[引用图片共{count}张]",
        gemini_quote_image_caption_timeout_seconds=3.0,
    )

    ctx = SimpleNamespace(
        is_group=True,
        group_id="123456",
        plaintext="fallback text",
        session_key="group:123456",
    )

    with patch("gemini_chat.handlers.build_event_context", return_value=ctx), \
         patch(
             "gemini_chat.handlers.parse_message_with_mentions",
             new=AsyncMock(return_value=("hello group", ["https://img.example/reply1.jpg"])),
         ), \
         patch("gemini_chat.handlers.extract_images", return_value=["https://img.example/main1.jpg"]), \
         patch(
             "gemini_chat.handlers._resolve_onebot_v12_image_urls",
             new=AsyncMock(return_value=["https://img.example/main1.jpg"]),
         ):
        payload = await build_request_context_payload(bot, event, plugin_config)

    assert payload.message_text == "hello group"
    assert payload.reply_images == ["https://img.example/reply1.jpg"]
    assert payload.image_urls == [
        "https://img.example/main1.jpg",
        "https://img.example/reply1.jpg",
    ]


@pytest.mark.asyncio
async def test_build_request_context_payload_private_uses_plaintext():
    from gemini_chat.handlers import build_request_context_payload

    bot = MagicMock()
    event = MagicMock()
    event.original_message = []

    plugin_config = SimpleNamespace(gemini_max_images=3)
    ctx = SimpleNamespace(
        is_group=False,
        group_id=None,
        plaintext="hello private",
        session_key="private:10001",
    )

    with patch("gemini_chat.handlers.build_event_context", return_value=ctx), \
         patch("gemini_chat.handlers.extract_images", return_value=[]), \
         patch(
             "gemini_chat.handlers._resolve_onebot_v12_image_urls",
             new=AsyncMock(return_value=[]),
         ):
        payload = await build_request_context_payload(bot, event, plugin_config)

    assert payload.message_text == "hello private"
    assert payload.reply_images == []
    assert payload.image_urls == []
