from __future__ import annotations


def test_transcript_builder_renders_placeholders_and_msg_id():
    from mika_chat_core.utils.transcript_builder import build_transcript_block, build_transcript_lines

    history = [
        {"role": "user", "message_id": "m1", "content": "[Alice(1)]: 看这个"},
        {
            "role": "user",
            "message_id": "m2",
            "content": [
                {"type": "text", "text": "还有表情"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/e.png"},
                    "mika_media": {"kind": "emoji", "id": "emoabc456", "ref": "mface-1"},
                },
            ],
        },
        {"role": "assistant", "message_id": "m3", "content": "好的"},
    ]

    lines = build_transcript_lines(history, bot_name="Mika", max_lines=10, line_max_chars=240)
    block = build_transcript_block(lines)
    assert "Alice(1): 看这个" in block.text
    assert "emoji:emoabc456" in block.text
    assert "<msg_id:m2>" in block.text
    assert "Mika: 好的" in block.text

