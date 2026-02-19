"""OneBot v11/v12 兼容性回归测试。"""

from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_check_proactive_supports_session_id_fallback():
    import mika_chat_core.matchers as m
    from mika_chat_core.contracts import Author, ContentPart, EventEnvelope

    old_enabled = getattr(m.plugin_config, "mika_active_reply_ltm_enabled", True)
    old_active_whitelist = list(getattr(m.plugin_config, "mika_active_reply_whitelist", []))
    old_group_whitelist = list(getattr(m.plugin_config, "mika_group_whitelist", []))
    old_probability = getattr(m.plugin_config, "mika_active_reply_probability", 1.0)
    old_keywords = list(getattr(m.plugin_config, "mika_proactive_keywords", []))
    old_keyword_cooldown = getattr(m.plugin_config, "mika_proactive_keyword_cooldown", 0)
    old_cooldowns = dict(m._proactive_cooldowns)

    try:
        m.plugin_config.mika_active_reply_ltm_enabled = True
        m.plugin_config.mika_active_reply_whitelist = []
        m.plugin_config.mika_group_whitelist = []
        m.plugin_config.mika_active_reply_probability = 1.0
        m.plugin_config.mika_proactive_keywords = ["mika"]
        m.plugin_config.mika_proactive_keyword_cooldown = 0
        m._proactive_cooldowns.clear()

        envelope = EventEnvelope(
            schema_version=1,
            session_id="group:123456",
            platform="test",
            protocol="test",
            message_id="m-1",
            timestamp=0.0,
            author=Author(id="10001", nickname="user"),
            bot_self_id="3932370959",
            content_parts=[ContentPart(kind="text", text="mika在吗")],
            meta={"group_id": "123456", "user_id": "10001", "is_group": True, "is_tome": False},
        )
        assert await m.check_proactive(envelope) is True
    finally:
        m.plugin_config.mika_active_reply_ltm_enabled = old_enabled
        m.plugin_config.mika_active_reply_whitelist = old_active_whitelist
        m.plugin_config.mika_group_whitelist = old_group_whitelist
        m.plugin_config.mika_active_reply_probability = old_probability
        m.plugin_config.mika_proactive_keywords = old_keywords
        m.plugin_config.mika_proactive_keyword_cooldown = old_keyword_cooldown
        m._proactive_cooldowns.clear()
        m._proactive_cooldowns.update(old_cooldowns)


@pytest.mark.asyncio
async def test_extract_and_resolve_images_dedupes_urls():
    from mika_chat_core.utils.image_processor import extract_and_resolve_images

    class _FakePlatformApiPort:
        @staticmethod
        def capabilities():
            return MagicMock(supports_file_resolve=True)

        @staticmethod
        async def resolve_file_url(file_id: str) -> str | None:
            if file_id == "f1":
                return "https://example.com/from-file-id.jpg"
            return None

    message = [
        {"type": "image", "data": {"url": "https://example.com/a.jpg"}},
        {"type": "image", "data": {"url": "https://example.com/a.jpg"}},  # duplicate
        {"type": "image", "data": {"file_id": "f1"}},
        {"type": "image", "data": {"file_id": "f1"}},  # duplicate
    ]

    urls = await extract_and_resolve_images(
        message,
        max_images=10,
        platform_api=_FakePlatformApiPort(),
    )
    assert urls == [
        "https://example.com/a.jpg",
        "https://example.com/from-file-id.jpg",
    ]
