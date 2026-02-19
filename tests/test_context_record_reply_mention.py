"""上下文记录语义化测试（引用/@/降级占位）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope


def _mock_group_envelope(*, plaintext: str = "你现在是啥专业", message_id: int = 3003) -> EventEnvelope:
    return EventEnvelope(
        schema_version=1,
        session_id="group:1001",
        platform="test",
        protocol="test",
        message_id=str(message_id),
        timestamp=0.0,
        author=Author(id="2002", nickname="粉毛丸子头单推"),
        bot_self_id="3932370959",
        content_parts=[
            ContentPart(kind="reply", target_id="111"),
            ContentPart(kind="mention", target_id="327516805", text="@327516805"),
            ContentPart(kind="text", text=plaintext),
        ],
        meta={"group_id": "1001", "user_id": "2002", "is_group": True, "is_tome": False},
    )


@pytest.mark.asyncio
async def test_cache_images_records_rich_reply_and_mention_text():
    from mika_chat_core import matchers

    envelope = _mock_group_envelope()
    matchers.plugin_config.mika_group_whitelist = []
    matchers.plugin_config.mika_max_images = 4

    mock_client = AsyncMock()
    mock_client.get_context = AsyncMock(return_value=[])
    mock_client.add_message = AsyncMock()

    image_cache = MagicMock()
    image_cache.record_message = MagicMock()
    image_cache.cache_images = MagicMock()

    parsed = "[引用 星鱼 的消息: 已经选不了了] @星鱼 你现在是啥专业"

    with (
        patch("mika_chat_core.matchers.resolve_image_urls", AsyncMock(return_value=[])),
        patch("mika_chat_core.matchers.get_image_cache", return_value=image_cache),
        patch("mika_chat_core.matchers.parse_message_with_mentions", AsyncMock(return_value=(parsed, []))),
        patch("mika_chat_core.matchers.get_runtime_client", return_value=mock_client),
    ):
        await matchers._cache_images(envelope)

    mock_client.add_message.assert_awaited_once()
    kwargs = mock_client.add_message.await_args.kwargs
    assert "content" in kwargs
    assert "[引用 星鱼 的消息: 已经选不了了]" in kwargs["content"]
    assert "@星鱼" in kwargs["content"]


@pytest.mark.asyncio
async def test_cache_images_fallback_when_rich_parse_fails():
    from mika_chat_core import matchers

    envelope = _mock_group_envelope()
    matchers.plugin_config.mika_group_whitelist = []
    matchers.plugin_config.mika_max_images = 4

    mock_client = AsyncMock()
    mock_client.get_context = AsyncMock(return_value=[])
    mock_client.add_message = AsyncMock()

    image_cache = MagicMock()
    image_cache.record_message = MagicMock()
    image_cache.cache_images = MagicMock()

    with (
        patch("mika_chat_core.matchers.resolve_image_urls", AsyncMock(return_value=[])),
        patch("mika_chat_core.matchers.get_image_cache", return_value=image_cache),
        patch(
            "mika_chat_core.matchers.parse_message_with_mentions",
            AsyncMock(side_effect=RuntimeError("parse fail")),
        ),
        patch("mika_chat_core.matchers.get_runtime_client", return_value=mock_client),
    ):
        await matchers._cache_images(envelope)

    mock_client.add_message.assert_awaited_once()
    kwargs = mock_client.add_message.await_args.kwargs
    assert "content" in kwargs
    assert "[引用消息]" in kwargs["content"]
    assert "@327516805" in kwargs["content"]
    assert "你现在是啥专业" in kwargs["content"]
