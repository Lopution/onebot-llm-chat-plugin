import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_safe_send_falls_back_without_kwargs():
    from mika_chat_core.utils.safe_api import safe_send

    bot = MagicMock()
    bot.send = AsyncMock(side_effect=[Exception("no kwargs"), None])

    event = MagicMock()
    ok = await safe_send(bot, event, "hello", reply_message=True, at_sender=False)

    assert ok is True
    assert bot.send.await_count == 2
    first = bot.send.await_args_list[0]
    second = bot.send.await_args_list[1]
    assert first.kwargs == {"reply_message": True, "at_sender": False}
    assert second.kwargs == {}


@pytest.mark.asyncio
async def test_safe_call_api_returns_none_on_error():
    from mika_chat_core.utils.safe_api import safe_call_api

    bot = MagicMock()
    bot.call_api = AsyncMock(side_effect=Exception("boom"))

    res = await safe_call_api(bot, "some_api", a=1)
    assert res is None

