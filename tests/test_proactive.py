
"""
测试 proactive 主动回复逻辑
"""

import time
from unittest.mock import MagicMock

import pytest
from mika_chat_core.matchers import check_proactive
from nonebot.adapters.onebot.v11 import GroupMessageEvent

import mika_chat_core.matchers as m


def mock_event(text="hello", group_id=123, user_id=456, to_me=False):
    """创建模拟的群消息事件"""
    event = MagicMock(spec=GroupMessageEvent)
    event.group_id = group_id
    event.user_id = user_id
    event.to_me = to_me
    event.get_plaintext.return_value = text
    # matchers.check_proactive 依赖 event.message 遍历图片段
    event.message = []
    return event


@pytest.mark.asyncio
async def test_proactive_keyword_trigger():
    """测试关键词触发"""
    # Set config
    m.plugin_config.gemini_proactive_keywords = ["Mika"]
    m.plugin_config.gemini_proactive_rate = 1.0  # Always trigger
    m.plugin_config.gemini_proactive_cooldown = 0
    m.plugin_config.gemini_proactive_ignore_len = 4
    m.plugin_config.gemini_group_whitelist = []
    m.plugin_config.gemini_heat_threshold = 10
    m.plugin_config.gemini_proactive_cooldown_messages = 0
    m.plugin_config.gemini_proactive_keyword_cooldown = 0
    
    # 清理冷却状态
    m._proactive_cooldowns.clear()
    
    event_hit = mock_event(text="I love Mika")
    res = await check_proactive(event_hit)
    assert res is True, "Should trigger for keyword 'Mika'"


@pytest.mark.asyncio
async def test_proactive_no_keyword():
    """测试无关键词不触发"""
    m.plugin_config.gemini_proactive_keywords = ["Mika"]
    m.plugin_config.gemini_proactive_rate = 1.0
    m.plugin_config.gemini_proactive_cooldown = 0
    m.plugin_config.gemini_proactive_ignore_len = 4
    m.plugin_config.gemini_group_whitelist = []
    m.plugin_config.gemini_heat_threshold = 10
    m.plugin_config.gemini_proactive_cooldown_messages = 0
    m.plugin_config.gemini_proactive_keyword_cooldown = 0
    
    event_miss = mock_event(text="Hello world")
    res = await check_proactive(event_miss)
    assert res is False, "Should not trigger without keyword"


@pytest.mark.asyncio
async def test_proactive_at_mention_exclusion():
    """测试 @提及时不触发"""
    m.plugin_config.gemini_proactive_keywords = ["Mika"]
    m.plugin_config.gemini_proactive_rate = 1.0
    m.plugin_config.gemini_proactive_cooldown = 0
    m.plugin_config.gemini_proactive_ignore_len = 4
    m.plugin_config.gemini_group_whitelist = []
    m.plugin_config.gemini_heat_threshold = 10
    m.plugin_config.gemini_proactive_cooldown_messages = 0
    m.plugin_config.gemini_proactive_keyword_cooldown = 0
    
    event_at = mock_event(text="Mika", to_me=True)
    res = await check_proactive(event_at)
    assert res is False, "Should not trigger if already @mentioned"


@pytest.mark.asyncio
async def test_proactive_cooldown():
    """测试冷却时间逻辑"""
    m.plugin_config.gemini_proactive_keywords = ["Mika"]
    m.plugin_config.gemini_proactive_rate = 1.0
    m.plugin_config.gemini_proactive_cooldown = 100
    m.plugin_config.gemini_proactive_ignore_len = 4
    m.plugin_config.gemini_group_whitelist = []
    m.plugin_config.gemini_heat_threshold = 10
    m.plugin_config.gemini_proactive_cooldown_messages = 0
    m.plugin_config.gemini_proactive_keyword_cooldown = 0
    
    # 设置冷却时间戳为当前时间，应该阻止触发
    m._proactive_cooldowns['123'] = time.time()
    
    event_hit = mock_event(text="I love Mika")
    res = await check_proactive(event_hit)
    assert res is False, "Should be blocked by cooldown"
