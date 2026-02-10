from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope, SendMessageAction
from mika_chat_core.engine import ChatEngine


class _DummyHostPort:
    def __init__(self) -> None:
        self.called = False

    def resolve_event(self, _envelope: EventEnvelope):
        self.called = True
        return None


def _envelope(*, intent: str) -> EventEnvelope:
    return EventEnvelope(
        schema_version=1,
        session_id="group:10001" if intent != "private" else "private:10001",
        platform="onebot_v11",
        protocol="onebot",
        message_id="msg-1",
        timestamp=1.0,
        author=Author(id="42", nickname="alice", role="member"),
        content_parts=[ContentPart(kind="text", text="hello")],
        meta={"intent": intent, "group_id": "10001", "user_id": "42"},
    )


@pytest.mark.asyncio
async def test_engine_handle_event_ignores_host_event_port_when_dispatch_disabled():
    host_port = _DummyHostPort()
    ports = SimpleNamespace(host_events=host_port)

    actions = await ChatEngine.handle_event(_envelope(intent="reset"), ports, dispatch=False)

    assert len(actions) == 1
    assert isinstance(actions[0], SendMessageAction)
    assert host_port.called is False


@pytest.mark.asyncio
async def test_engine_handle_event_dispatch_requires_message_port_even_with_host_port():
    host_port = _DummyHostPort()
    ports = SimpleNamespace(host_events=host_port)
    with pytest.raises(ValueError):
        await ChatEngine.handle_event(_envelope(intent="group"), ports, dispatch=True)
    assert host_port.called is False


@pytest.mark.asyncio
async def test_engine_handle_event_without_host_port_still_returns_actions():
    envelope = _envelope(intent="private")
    actions = await ChatEngine.handle_event(envelope, ports=None, settings=None, dispatch=False)
    assert len(actions) == 1
    assert isinstance(actions[0], SendMessageAction)


@pytest.mark.asyncio
async def test_engine_handle_event_dispatch_with_message_port_succeeds():
    envelope = _envelope(intent="group")
    message_port = AsyncMock()
    message_port.send_message = AsyncMock(return_value={"ok": True})
    ports = SimpleNamespace(host_events=_DummyHostPort(), message=message_port)

    actions = await ChatEngine.handle_event(envelope, ports=ports, dispatch=True)

    assert len(actions) == 1
    assert isinstance(actions[0], SendMessageAction)
    message_port.send_message.assert_awaited_once()
