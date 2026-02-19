from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope, NoopAction, SendMessageAction
from mika_chat_core.engine import ChatEngine
from mika_chat_core import runtime as runtime_module


class _DummyHostPort:
    def __init__(self, runtime_ref=None) -> None:
        self.called = False
        self.runtime_ref = runtime_ref

    def resolve_event(self, _envelope: EventEnvelope):
        self.called = True
        return self.runtime_ref


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
async def test_engine_handle_event_returns_noop_when_explicit_intent_without_runtime_ref():
    host_port = _DummyHostPort()
    ports = SimpleNamespace(host_events=host_port)

    actions = await ChatEngine.handle_event(_envelope(intent="reset"), ports, dispatch=False)

    assert len(actions) == 1
    assert isinstance(actions[0], NoopAction)
    assert actions[0].reason == "host_runtime_unavailable"
    assert host_port.called is True


@pytest.mark.asyncio
async def test_engine_handle_event_dispatch_noops_without_runtime_ref():
    host_port = _DummyHostPort()
    ports = SimpleNamespace(host_events=host_port)
    actions = await ChatEngine.handle_event(_envelope(intent="group"), ports, dispatch=True)
    assert len(actions) == 1
    assert isinstance(actions[0], NoopAction)
    assert actions[0].reason == "host_runtime_unavailable"
    assert host_port.called is True


@pytest.mark.asyncio
async def test_engine_handle_event_without_host_port_with_explicit_intent_returns_noop():
    envelope = _envelope(intent="group")
    actions = await ChatEngine.handle_event(envelope, ports=None, settings=None, dispatch=False)
    assert len(actions) == 1
    assert isinstance(actions[0], NoopAction)
    assert actions[0].reason == "host_runtime_unavailable"


@pytest.mark.asyncio
async def test_engine_handle_event_dispatch_with_message_port_succeeds_without_explicit_intent():
    envelope = _envelope(intent="group")
    envelope.meta.pop("intent", None)
    message_port = AsyncMock()
    message_port.send_message = AsyncMock(return_value={"ok": True})
    ports = SimpleNamespace(host_events=_DummyHostPort(), message=message_port)

    actions = await ChatEngine.handle_event(envelope, ports=ports, dispatch=True)

    assert len(actions) == 1
    assert isinstance(actions[0], SendMessageAction)
    message_port.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_engine_handle_event_delegates_to_private_handler_when_runtime_ref_available(monkeypatch):
    bot = object()
    event = object()
    host_port = _DummyHostPort(runtime_ref=(bot, event))
    ports = SimpleNamespace(host_events=host_port)

    mock_private = AsyncMock()
    mock_group = AsyncMock()
    mock_reset = AsyncMock()

    monkeypatch.setattr("mika_chat_core.handlers.handle_private", mock_private)
    monkeypatch.setattr("mika_chat_core.handlers.handle_group", mock_group)
    monkeypatch.setattr("mika_chat_core.handlers.handle_reset", mock_reset)
    runtime_module.set_client("fake-client")

    settings = object()
    actions = await ChatEngine.handle_event(_envelope(intent="private"), ports, settings=settings, dispatch=False)

    assert len(actions) == 1
    assert isinstance(actions[0], NoopAction)
    assert actions[0].reason == "handled_by_host_runtime"
    mock_private.assert_awaited_once()
    call_args = mock_private.await_args
    assert len(call_args.args) == 1
    envelope = call_args.args[0]
    assert isinstance(envelope, EventEnvelope)
    assert envelope.meta.get("intent") == "private"
    assert call_args.kwargs["plugin_config"] is settings
    assert call_args.kwargs["mika_client"] == "fake-client"
    mock_group.assert_not_awaited()
    mock_reset.assert_not_awaited()
