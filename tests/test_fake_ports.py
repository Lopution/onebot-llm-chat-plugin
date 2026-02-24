from __future__ import annotations

import pytest

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope, NoopAction, SendMessageAction
from mika_chat_core.engine import ChatEngine
from mika_chat_core.ports.fake_ports import FakePorts


def _build_envelope(*, parts: list[ContentPart]) -> EventEnvelope:
    return EventEnvelope(
        schema_version=1,
        session_id="group:9527",
        platform="onebot_v11",
        protocol="onebot",
        message_id="10101",
        timestamp=1730000000.0,
        author=Author(id="42", nickname="alice", role="member"),
        content_parts=parts,
        meta={"group_id": "9527", "user_id": "42"},
    )


@pytest.mark.asyncio
async def test_engine_envelope_to_actions_and_dispatch_with_fake_message_port():
    ports = FakePorts()
    envelope = _build_envelope(parts=[ContentPart(kind="text", text="hello world")])

    actions = ChatEngine.envelope_to_actions(envelope, reply_text="收到")
    assert len(actions) == 1
    assert isinstance(actions[0], SendMessageAction)

    results = await ChatEngine.dispatch_actions(actions, ports.message)
    assert len(results) == 1
    assert len(ports.message.sent_actions) == 1
    assert ports.message.sent_actions[0].parts[0].text == "收到"
    assert results[0]["session_id"] == "group:9527"


@pytest.mark.asyncio
async def test_engine_handle_event_without_dispatch_returns_actions_only():
    ports = FakePorts()
    envelope = _build_envelope(parts=[ContentPart(kind="text", text="hello world")])

    actions = await ChatEngine.handle_event(
        envelope,
        ports,
        reply_text="仅返回动作",
        dispatch=False,
    )
    assert len(actions) == 1
    assert isinstance(actions[0], SendMessageAction)
    assert actions[0].parts[0].text == "仅返回动作"
    assert ports.message.sent_actions == []


@pytest.mark.asyncio
async def test_engine_handle_event_with_dispatch_uses_ports_bundle():
    ports = FakePorts()
    envelope = _build_envelope(parts=[ContentPart(kind="text", text="hello world")])

    actions = await ChatEngine.handle_event(
        envelope,
        ports,
        reply_text="触发发送",
        dispatch=True,
    )
    assert len(actions) == 1
    assert len(ports.message.sent_actions) == 1
    assert ports.message.sent_actions[0].parts[0].text == "触发发送"


@pytest.mark.asyncio
async def test_engine_returns_noop_for_empty_input():
    ports = FakePorts()
    envelope = _build_envelope(parts=[])

    actions = ChatEngine.envelope_to_actions(envelope)
    assert len(actions) == 1
    assert isinstance(actions[0], NoopAction)
    assert actions[0].reason == "empty_input"

    results = await ChatEngine.dispatch_actions(actions, ports.message)
    assert results == []
    assert ports.message.sent_actions == []


@pytest.mark.asyncio
async def test_fake_asset_and_clock_ports():
    ports = FakePorts()
    ports.asset.assets["asset://1"] = b"abc"

    content = await ports.asset.download("asset://1")
    assert content == b"abc"

    with pytest.raises(KeyError):
        await ports.asset.download("asset://missing")

    assert ports.clock.now() == 0.0
    assert ports.clock.monotonic() == 0.0
    ports.clock.tick(2.5)
    assert ports.clock.now() == 2.5
    assert ports.clock.monotonic() == 2.5
