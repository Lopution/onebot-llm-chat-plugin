"""OneBot v11/v12 兼容性回归测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_check_proactive_supports_session_id_fallback():
    import mika_chat_core.matchers as m

    class Event:
        to_me = False
        message = []

        @staticmethod
        def get_session_id() -> str:
            return "group_123456_10001"

        @staticmethod
        def get_plaintext() -> str:
            return "mika在吗"

    old_enabled = getattr(m.plugin_config, "gemini_active_reply_ltm_enabled", True)
    old_active_whitelist = list(getattr(m.plugin_config, "gemini_active_reply_whitelist", []))
    old_group_whitelist = list(getattr(m.plugin_config, "gemini_group_whitelist", []))
    old_probability = getattr(m.plugin_config, "gemini_active_reply_probability", 1.0)
    old_keywords = list(getattr(m.plugin_config, "gemini_proactive_keywords", []))
    old_keyword_cooldown = getattr(m.plugin_config, "gemini_proactive_keyword_cooldown", 0)
    old_cooldowns = dict(m._proactive_cooldowns)

    try:
        m.plugin_config.gemini_active_reply_ltm_enabled = True
        m.plugin_config.gemini_active_reply_whitelist = []
        m.plugin_config.gemini_group_whitelist = []
        m.plugin_config.gemini_active_reply_probability = 1.0
        m.plugin_config.gemini_proactive_keywords = ["mika"]
        m.plugin_config.gemini_proactive_keyword_cooldown = 0
        m._proactive_cooldowns.clear()

        assert await m.check_proactive(Event()) is True
    finally:
        m.plugin_config.gemini_active_reply_ltm_enabled = old_enabled
        m.plugin_config.gemini_active_reply_whitelist = old_active_whitelist
        m.plugin_config.gemini_group_whitelist = old_group_whitelist
        m.plugin_config.gemini_active_reply_probability = old_probability
        m.plugin_config.gemini_proactive_keywords = old_keywords
        m.plugin_config.gemini_proactive_keyword_cooldown = old_keyword_cooldown
        m._proactive_cooldowns.clear()
        m._proactive_cooldowns.update(old_cooldowns)


@pytest.mark.asyncio
async def test_extract_and_resolve_images_dedupes_urls():
    from mika_chat_core.utils.image_processor import extract_and_resolve_images

    bot = MagicMock()

    async def _call_api(api: str, **data):
        if api == "get_file" and data.get("file_id") == "f1":
            return {"url": "https://example.com/from-file-id.jpg"}
        return None

    bot.call_api = AsyncMock(side_effect=_call_api)

    message = [
        {"type": "image", "data": {"url": "https://example.com/a.jpg"}},
        {"type": "image", "data": {"url": "https://example.com/a.jpg"}},  # duplicate
        {"type": "image", "data": {"file_id": "f1"}},
        {"type": "image", "data": {"file_id": "f1"}},  # duplicate
    ]

    urls = await extract_and_resolve_images(bot, message, max_images=10)
    assert urls == [
        "https://example.com/a.jpg",
        "https://example.com/from-file-id.jpg",
    ]
