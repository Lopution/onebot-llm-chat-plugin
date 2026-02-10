from __future__ import annotations

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope
from mika_chat_core.engine import ChatEngine
from mika_chat_core.event_envelope import build_event_envelope


class _Segment:
    def __init__(self, seg_type: str, data: dict):
        self.type = seg_type
        self.data = data


class _Sender:
    def __init__(self, *, nickname: str = "", card: str = "", role: str = ""):
        self.nickname = nickname
        self.card = card
        self.role = role


class _Bot:
    type = "OneBot V11"


class _Event:
    def __init__(self):
        self.user_id = 10001
        self.group_id = 20002
        self.message_id = 30003
        self.to_me = True
        self.time = 1730000000
        self.sender = _Sender(nickname="alice", card="AliceCard", role="member")
        self.original_message = [
            _Segment("text", {"text": "你好"}),
            _Segment("at", {"qq": "3932370959"}),
            _Segment("reply", {"id": "9988"}),
            _Segment("image", {"url": "https://example.com/a.png"}),
            _Segment("record", {"file": "voice.amr"}),
        ]

    def get_plaintext(self) -> str:
        return "你好 @3932370959"

    def get_session_id(self) -> str:
        return "group_20002_10001"


def test_build_event_envelope_keeps_semantic_parts():
    envelope = build_event_envelope(_Bot(), _Event(), protocol="onebot")
    assert envelope.platform == "onebot_v11"
    assert envelope.protocol == "onebot"
    assert envelope.session_id == "group:20002"
    assert envelope.author.nickname == "AliceCard"

    kinds = [part.kind for part in envelope.content_parts]
    assert kinds == ["text", "mention", "reply", "image", "attachment"]
    assert envelope.content_parts[1].target_id == "3932370959"
    assert envelope.content_parts[2].target_id == "9988"
    assert envelope.content_parts[3].asset_ref == "https://example.com/a.png"


def test_build_event_envelope_fallback_plaintext():
    event = _Event()
    event.original_message = []
    envelope = build_event_envelope(_Bot(), event, protocol="onebot")
    assert len(envelope.content_parts) == 1
    assert envelope.content_parts[0].kind == "text"
    assert envelope.content_parts[0].text == "你好 @3932370959"


def test_engine_bridge_envelope_to_legacy():
    envelope = EventEnvelope(
        schema_version=1,
        session_id="group:20002",
        platform="onebot_v11",
        protocol="onebot",
        message_id="30003",
        timestamp=1730000000.0,
        author=Author(id="10001", nickname="alice", role="member"),
        content_parts=[
            ContentPart(kind="text", text="hello"),
            ContentPart(kind="mention", target_id="3932370959", text="@bot"),
            ContentPart(kind="reply", target_id="9988"),
            ContentPart(kind="image", asset_ref="https://example.com/a.png"),
            ContentPart(kind="attachment", asset_ref="voice.amr"),
        ],
        meta={"group_id": "20002", "user_id": "10001"},
    )

    session = ChatEngine.envelope_to_chat_session(envelope)
    message = ChatEngine.envelope_to_chat_message(envelope)

    assert session.group_id == "20002"
    assert session.is_private is False
    assert message.user_id == "10001"
    assert message.group_id == "20002"
    assert message.mentions == ["3932370959"]
    assert message.images == ["https://example.com/a.png"]
    assert "[reply:9988]" in message.text
    assert "[图片]" in message.text
    assert "[附件]" in message.text
