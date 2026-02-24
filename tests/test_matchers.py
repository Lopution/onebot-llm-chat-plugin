"""matchers 基础行为测试（EventEnvelope 版本）。"""

from __future__ import annotations

import pytest

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope
from mika_chat_core.matchers import _is_private_message, check_at_me_anywhere


def _group_envelope(*, to_me: bool, mentioned: bool = False, self_message: bool = False) -> EventEnvelope:
    bot_id = "12345"
    author_id = bot_id if self_message else "2002"
    parts = [ContentPart(kind="text", text="hello")]
    if mentioned:
        parts.append(ContentPart(kind="mention", target_id=bot_id, text="@Mika"))
    return EventEnvelope(
        schema_version=1,
        session_id="group:1001",
        platform="test",
        protocol="test",
        message_id="m-1",
        timestamp=0.0,
        author=Author(id=author_id, nickname="user"),
        bot_self_id=bot_id,
        content_parts=parts,
        meta={"group_id": "1001", "user_id": author_id, "is_group": True, "is_tome": to_me},
    )


def _private_envelope(*, self_message: bool = False, message_sent: bool = False) -> EventEnvelope:
    bot_id = "12345"
    author_id = bot_id if self_message else "2002"
    return EventEnvelope(
        schema_version=1,
        session_id="private:2002",
        platform="test",
        protocol="test",
        message_id="m-2",
        timestamp=0.0,
        author=Author(id=author_id, nickname="user"),
        bot_self_id=bot_id,
        content_parts=[ContentPart(kind="text", text="hi")],
        meta={
            "group_id": "",
            "user_id": author_id,
            "is_group": False,
            "is_tome": False,
            "post_type": "message_sent" if message_sent else "",
            "message_sent_type": "self" if message_sent else "",
        },
    )


@pytest.mark.asyncio
async def test_check_at_me_anywhere_hits_to_me():
    assert await check_at_me_anywhere(_group_envelope(to_me=True)) is True


@pytest.mark.asyncio
async def test_check_at_me_anywhere_hits_mention():
    assert await check_at_me_anywhere(_group_envelope(to_me=False, mentioned=True)) is True


@pytest.mark.asyncio
async def test_check_at_me_anywhere_miss():
    assert await check_at_me_anywhere(_group_envelope(to_me=False, mentioned=False)) is False


@pytest.mark.asyncio
async def test_check_at_me_anywhere_ignores_self_sender():
    assert await check_at_me_anywhere(_group_envelope(to_me=True, mentioned=True, self_message=True)) is False


@pytest.mark.asyncio
async def test_is_private_message_true():
    assert await _is_private_message(_private_envelope()) is True


@pytest.mark.asyncio
async def test_is_private_message_false_for_message_sent():
    assert await _is_private_message(_private_envelope(message_sent=True)) is False


@pytest.mark.asyncio
async def test_is_private_message_false_for_self_message():
    assert await _is_private_message(_private_envelope(self_message=True)) is False
