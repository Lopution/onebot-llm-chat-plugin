from __future__ import annotations


def test_proactive_transcript_appends_msg_id_for_media_placeholders():
    from mika_chat_core.handlers_proactive import build_proactive_chatroom_injection

    history = [
        {
            "role": "user",
            "message_id": "m1",
            "content": [
                {"type": "text", "text": "看看这个"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
            ],
        },
        {
            "role": "user",
            "message_id": "m2",
            "content": [
                {"type": "text", "text": "还有这个表情"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/e.png"},
                    "mika_media": {"kind": "emoji", "id": "emoabc456", "ref": "mface-1"},
                },
            ],
        },
    ]

    injection = build_proactive_chatroom_injection(
        history,
        bot_name="Mika",
        max_lines=10,
        trigger_message="啥意思",
        trigger_sender="Tester",
    )

    assert "[picid:" in injection
    assert "emoji:emoabc456" in injection
    assert "<msg_id:m1>" in injection
    assert "<msg_id:m2>" in injection

