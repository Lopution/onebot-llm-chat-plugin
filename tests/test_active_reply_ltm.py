"""主动回复 LTM 门控测试。"""

from unittest.mock import MagicMock

import pytest

import mika_chat_core.matchers as m


def _mock_group_event(text: str = "hello", group_id: int = 123456, user_id: int = 10001):
    event = MagicMock()
    event.group_id = group_id
    event.user_id = user_id
    event.to_me = False
    event.message = []
    event.get_plaintext.return_value = text
    return event


@pytest.mark.asyncio
async def test_check_proactive_disabled_by_ltm_gate():
    old_enabled = getattr(m.plugin_config, "mika_active_reply_ltm_enabled", True)
    old_keywords = list(getattr(m.plugin_config, "mika_proactive_keywords", []))
    old_whitelist = list(getattr(m.plugin_config, "mika_group_whitelist", []))
    try:
        m.plugin_config.mika_active_reply_ltm_enabled = False
        m.plugin_config.mika_proactive_keywords = ["Mika"]
        m.plugin_config.mika_group_whitelist = []

        result = await m.check_proactive(_mock_group_event(text="Mika 在吗"))
        assert result is False
    finally:
        m.plugin_config.mika_active_reply_ltm_enabled = old_enabled
        m.plugin_config.mika_proactive_keywords = old_keywords
        m.plugin_config.mika_group_whitelist = old_whitelist


@pytest.mark.asyncio
async def test_check_proactive_blocked_by_active_reply_whitelist():
    old_enabled = getattr(m.plugin_config, "mika_active_reply_ltm_enabled", True)
    old_probability = getattr(m.plugin_config, "mika_active_reply_probability", 1.0)
    old_active_whitelist = list(getattr(m.plugin_config, "mika_active_reply_whitelist", []))
    old_keywords = list(getattr(m.plugin_config, "mika_proactive_keywords", []))
    old_group_whitelist = list(getattr(m.plugin_config, "mika_group_whitelist", []))
    old_keyword_cooldown = getattr(m.plugin_config, "mika_proactive_keyword_cooldown", 0)
    old_cooldowns = dict(m._proactive_cooldowns)
    try:
        m.plugin_config.mika_active_reply_ltm_enabled = True
        m.plugin_config.mika_active_reply_probability = 1.0
        m.plugin_config.mika_active_reply_whitelist = ["999999"]
        m.plugin_config.mika_proactive_keywords = ["Mika"]
        m.plugin_config.mika_group_whitelist = []
        m.plugin_config.mika_proactive_keyword_cooldown = 0
        m._proactive_cooldowns.clear()

        result = await m.check_proactive(_mock_group_event(text="Mika 在吗", group_id=123456))
        assert result is False
    finally:
        m.plugin_config.mika_active_reply_ltm_enabled = old_enabled
        m.plugin_config.mika_active_reply_probability = old_probability
        m.plugin_config.mika_active_reply_whitelist = old_active_whitelist
        m.plugin_config.mika_proactive_keywords = old_keywords
        m.plugin_config.mika_group_whitelist = old_group_whitelist
        m.plugin_config.mika_proactive_keyword_cooldown = old_keyword_cooldown
        m._proactive_cooldowns.clear()
        m._proactive_cooldowns.update(old_cooldowns)
