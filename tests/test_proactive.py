"""测试 proactive 主动回复逻辑（EventEnvelope 驱动）。"""

from __future__ import annotations

import time

import pytest

import mika_chat_core.matchers as m
from mika_chat_core.contracts import Author, ContentPart, EventEnvelope
from mika_chat_core.matchers import check_proactive


def _mock_envelope(text: str = "hello", group_id: str = "123", user_id: str = "456", to_me: bool = False) -> EventEnvelope:
    return EventEnvelope(
        schema_version=1,
        session_id=f"group:{group_id}",
        platform="test",
        protocol="test",
        message_id="m-1",
        timestamp=0.0,
        author=Author(id=user_id, nickname="user"),
        bot_self_id="3932370959",
        content_parts=[ContentPart(kind="text", text=text)],
        meta={"group_id": group_id, "user_id": user_id, "is_group": True, "is_tome": to_me},
    )


@pytest.mark.asyncio
async def test_proactive_keyword_trigger():
    m.plugin_config.mika_proactive_keywords = ["Mika"]
    m.plugin_config.mika_proactive_rate = 1.0
    m.plugin_config.mika_proactive_cooldown = 0
    m.plugin_config.mika_proactive_ignore_len = 4
    m.plugin_config.mika_group_whitelist = []
    m.plugin_config.mika_heat_threshold = 10
    m.plugin_config.mika_proactive_cooldown_messages = 0
    m.plugin_config.mika_proactive_keyword_cooldown = 0
    m._proactive_cooldowns.clear()

    assert await check_proactive(_mock_envelope(text="I love Mika")) is True


@pytest.mark.asyncio
async def test_proactive_no_keyword():
    m.plugin_config.mika_proactive_keywords = ["Mika"]
    m.plugin_config.mika_proactive_rate = 1.0
    m.plugin_config.mika_proactive_cooldown = 0
    m.plugin_config.mika_proactive_ignore_len = 4
    m.plugin_config.mika_group_whitelist = []
    m.plugin_config.mika_heat_threshold = 10
    m.plugin_config.mika_proactive_cooldown_messages = 0
    m.plugin_config.mika_proactive_keyword_cooldown = 0

    assert await check_proactive(_mock_envelope(text="Hello world")) is False


@pytest.mark.asyncio
async def test_proactive_at_mention_exclusion():
    m.plugin_config.mika_proactive_keywords = ["Mika"]
    m.plugin_config.mika_proactive_rate = 1.0
    m.plugin_config.mika_proactive_cooldown = 0
    m.plugin_config.mika_proactive_ignore_len = 4
    m.plugin_config.mika_group_whitelist = []
    m.plugin_config.mika_heat_threshold = 10
    m.plugin_config.mika_proactive_cooldown_messages = 0
    m.plugin_config.mika_proactive_keyword_cooldown = 0

    assert await check_proactive(_mock_envelope(text="Mika", to_me=True)) is False


@pytest.mark.asyncio
async def test_proactive_cooldown():
    m.plugin_config.mika_proactive_keywords = ["Mika"]
    m.plugin_config.mika_proactive_rate = 1.0
    m.plugin_config.mika_proactive_cooldown = 100
    m.plugin_config.mika_proactive_ignore_len = 4
    m.plugin_config.mika_group_whitelist = []
    m.plugin_config.mika_heat_threshold = 10
    m.plugin_config.mika_proactive_cooldown_messages = 0
    m.plugin_config.mika_proactive_keyword_cooldown = 0

    m._proactive_cooldowns["123"] = time.monotonic()
    assert await check_proactive(_mock_envelope(text="I love Mika")) is False
