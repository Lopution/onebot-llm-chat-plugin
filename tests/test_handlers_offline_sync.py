from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_offline_sync_warns_when_platform_api_unavailable(caplog):
    from mika_chat_core import handlers

    config = SimpleNamespace(
        mika_offline_sync_enabled=True,
        mika_group_whitelist=["10001"],
        mika_history_count=20,
    )
    client = AsyncMock()
    client.is_persistent = True
    client.get_context = AsyncMock(return_value=[])
    client.add_message = AsyncMock()

    async def _no_sleep(_seconds: float) -> None:
        return None

    with patch.object(handlers, "get_config", return_value=config), patch.object(
        handlers, "get_mika_client", return_value=client
    ), patch.object(
        handlers, "get_runtime_platform_api_port", return_value=None
    ), patch(
        "mika_chat_core.handlers.asyncio.sleep", new=_no_sleep
    ):
        with caplog.at_level("WARNING"):
            await handlers._sync_offline_messages_task()

    assert "PlatformApiPort 未注册" in caplog.text
    client.add_message.assert_not_called()


@pytest.mark.asyncio
async def test_offline_sync_uses_platform_api_port():
    from mika_chat_core import handlers

    config = SimpleNamespace(
        mika_offline_sync_enabled=True,
        mika_group_whitelist=["10001"],
        mika_history_count=20,
    )
    client = AsyncMock()
    client.is_persistent = True
    client.get_context = AsyncMock(return_value=[])
    client.add_message = AsyncMock()

    class _FakePlatformApiPort:
        @staticmethod
        def capabilities():
            return SimpleNamespace(supports_history_fetch=True)

        @staticmethod
        async def fetch_conversation_history(conversation_id: str, limit: int = 20):
            assert conversation_id == "10001"
            assert limit == 20
            return [
                {
                    "message_id": "m-1",
                    "user_id": "20001",
                    "raw_message": "hello",
                    "sender": {"user_id": "20001", "nickname": "Alice", "card": ""},
                    "time": 1000,
                }
            ]

    async def _no_sleep(_seconds: float) -> None:
        return None

    with patch.object(handlers, "get_config", return_value=config), patch.object(
        handlers, "get_mika_client", return_value=client
    ), patch.object(
        handlers, "get_runtime_platform_api_port", return_value=_FakePlatformApiPort()
    ), patch(
        "mika_chat_core.handlers.asyncio.sleep", new=_no_sleep
    ):
        await handlers._sync_offline_messages_task()

    client.add_message.assert_awaited_once()
    kwargs = client.add_message.await_args.kwargs
    assert kwargs["group_id"] == "10001"
    assert kwargs["message_id"] == "m-1"
    assert kwargs["content"] == "[Alice(20001)]: hello"
