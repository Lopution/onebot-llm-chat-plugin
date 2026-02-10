from __future__ import annotations

import json

import pytest

from mika_chat_core.contracts import (
    Author,
    ChatMessage,
    ChatSession,
    ContentPart,
    EventEnvelope,
    NoopAction,
    SendMessageAction,
)


def test_content_part_rejects_unknown_kind():
    with pytest.raises(ValueError):
        ContentPart(kind="video")  # type: ignore[arg-type]


def test_event_envelope_round_trip_json_serializable():
    envelope = EventEnvelope(
        schema_version=1,
        session_id="group:123",
        platform="qq",
        protocol="onebot-v11",
        message_id="9988",
        timestamp=1730000000.0,
        author=Author(id="42", nickname="alice", role="member"),
        content_parts=[
            ContentPart(kind="text", text="hello"),
            ContentPart(kind="mention", target_id="10001", text="@bot"),
            ContentPart(kind="reply", target_id="556677"),
            ContentPart(kind="image", asset_ref="https://example.com/a.png"),
        ],
        meta={"source": "unit-test"},
        raw={"debug": True},
    )

    payload = envelope.to_dict()
    encoded = json.dumps(payload, ensure_ascii=False)
    decoded = json.loads(encoded)
    reconstructed = EventEnvelope.from_dict(decoded)

    assert reconstructed == envelope


def test_send_message_action_round_trip():
    action = SendMessageAction(
        type="send_message",
        session_id="group:123",
        parts=[ContentPart(kind="text", text="ok")],
        reply_to="778899",
        mentions=["10001"],
        meta={"trace_id": "abc"},
    )

    payload = action.to_dict()
    reconstructed = SendMessageAction.from_dict(payload)

    assert reconstructed == action


def test_noop_action_round_trip():
    action = NoopAction(type="noop", reason="cooldown", meta={"gate": "rate"})
    payload = action.to_dict()
    reconstructed = NoopAction.from_dict(payload)

    assert reconstructed == action


def test_legacy_chat_message_and_session_round_trip():
    msg = ChatMessage(
        role="user",
        text="test",
        user_id="1",
        group_id="2",
        message_id="3",
        mentions=["4"],
        images=["https://example.com/a.jpg"],
        raw={"source": "legacy"},
    )
    sess = ChatSession(user_id="1", group_id="2", is_private=False)

    assert ChatMessage.from_dict(msg.to_dict()) == msg
    assert ChatSession.from_dict(sess.to_dict()) == sess
