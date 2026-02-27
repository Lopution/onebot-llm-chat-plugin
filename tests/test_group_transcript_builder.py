from __future__ import annotations


def test_transcript_builder_renders_placeholders_and_msg_id():
    from mika_chat_core.utils.transcript_builder import build_transcript_block, build_transcript_lines

    history = [
        {"role": "user", "message_id": "m1", "timestamp": 1000.0, "content": "[Alice(1)]: 看这个"},
        {
            "role": "user",
            "message_id": "m2",
            "timestamp": 1060.0,
            "content": [
                {"type": "text", "text": "[Alice(1)]: 还有表情"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/e.png"},
                    "mika_media": {"kind": "emoji", "id": "emoabc456", "ref": "mface-1"},
                },
            ],
        },
        {"role": "assistant", "message_id": "m3", "timestamp": 1120.0, "content": "[Mika]: 好的"},
    ]

    lines = build_transcript_lines(history, bot_name="Mika", max_lines=10, line_max_chars=240)
    block = build_transcript_block(lines)
    assert "Alice: 看这个" in block.text
    assert "[2分钟前]" in block.text
    assert "emoji:emoabc456" in block.text
    assert "<msg_id:m2>" in block.text
    assert "Mika: 好的" in block.text
    assert "[刚刚]" in block.text


def test_transcript_builder_disambiguates_same_nickname_with_user_id_suffix():
    from mika_chat_core.utils.transcript_builder import build_transcript_block, build_transcript_lines

    history = [
        {"role": "user", "message_id": "m1", "timestamp": 1000.0, "content": "[Alex(1)]: hi"},
        {"role": "user", "message_id": "m2", "timestamp": 1001.0, "content": "[Alex(2)]: yo"},
    ]
    lines = build_transcript_lines(history, bot_name="Mika", max_lines=10, line_max_chars=240)
    block = build_transcript_block(lines)
    assert "Alex(1): hi" in block.text
    assert "Alex(2): yo" in block.text


def test_transcript_builder_participants_line_skips_bot_name():
    from mika_chat_core.utils.transcript_builder import build_participants_line

    lines = [
        "[刚刚] Alice: hi",
        "[刚刚] Mika: ok",
        "[刚刚] Bob: yo",
    ]
    out = build_participants_line(lines, bot_name="Mika", max_names=8, window_lines=60)
    assert "Alice" in out
    assert "Bob" in out
    assert "Mika" not in out
    assert "last: Bob" in out
