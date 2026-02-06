"""matchers 基础行为测试。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
from unittest.mock import MagicMock

import pytest

from gemini_chat.matchers import check_at_me_anywhere, _is_private_message


@dataclass
class _Seg:
    type: str
    data: Dict[str, str]


def _mock_bot(self_id: str = "12345") -> MagicMock:
    bot = MagicMock()
    bot.self_id = self_id
    bot.type = "OneBot V11"
    return bot


def _mock_group_event(*, to_me: bool, original_message: list[_Seg] | None = None) -> MagicMock:
    event = MagicMock()
    event.group_id = 1001
    event.user_id = 2002
    event.to_me = to_me
    event.original_message = original_message or []
    event.message = []
    event.get_plaintext.return_value = "hello"
    return event


@pytest.mark.asyncio
async def test_check_at_me_anywhere_hits_to_me():
    bot = _mock_bot("12345")
    event = _mock_group_event(to_me=True)
    assert await check_at_me_anywhere(bot, event) is True


@pytest.mark.asyncio
async def test_check_at_me_anywhere_hits_original_at():
    bot = _mock_bot("12345")
    event = _mock_group_event(
        to_me=False,
        original_message=[_Seg(type="at", data={"qq": "12345"})],
    )
    assert await check_at_me_anywhere(bot, event) is True


@pytest.mark.asyncio
async def test_check_at_me_anywhere_hits_original_mention():
    bot = _mock_bot("12345")
    event = _mock_group_event(
        to_me=False,
        original_message=[_Seg(type="mention", data={"user_id": "12345"})],
    )
    assert await check_at_me_anywhere(bot, event) is True


@pytest.mark.asyncio
async def test_check_at_me_anywhere_miss():
    bot = _mock_bot("12345")
    event = _mock_group_event(
        to_me=False,
        original_message=[_Seg(type="at", data={"qq": "99999"})],
    )
    assert await check_at_me_anywhere(bot, event) is False


@pytest.mark.asyncio
async def test_is_private_message_true():
    bot = _mock_bot("12345")
    event = MagicMock()
    event.user_id = 2002
    event.group_id = None
    event.get_plaintext.return_value = "hi"
    assert await _is_private_message(bot, event) is True


@pytest.mark.asyncio
async def test_is_private_message_false_for_group():
    bot = _mock_bot("12345")
    event = MagicMock()
    event.user_id = 2002
    event.group_id = 1001
    event.get_plaintext.return_value = "hi"
    assert await _is_private_message(bot, event) is False

