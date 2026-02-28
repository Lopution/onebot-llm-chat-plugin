from __future__ import annotations


def test_transcript_builder_renders_placeholders_and_msg_id():
    from mika_chat_core.utils.transcript_builder import build_transcript_block, build_transcript_lines
    from mika_chat_core.utils.speaker_labels import speaker_label_for_user_id

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
    assert f"{speaker_label_for_user_id('1')}: 看这个" in block.text
    assert "[2分钟前]" in block.text
    assert "emoji:emoabc456" in block.text
    assert "<msg_id:m2>" in block.text
    assert "Mika: 好的" in block.text
    assert "[刚刚]" in block.text
    assert "Alice" not in block.text


def test_transcript_builder_uses_stable_alias_per_user_id():
    from mika_chat_core.utils.transcript_builder import build_transcript_block, build_transcript_lines
    from mika_chat_core.utils.speaker_labels import speaker_label_for_user_id

    history = [
        {"role": "user", "message_id": "m1", "timestamp": 1000.0, "content": "[Alex(1)]: hi"},
        {"role": "user", "message_id": "m2", "timestamp": 1001.0, "content": "[Alex(2)]: yo"},
    ]
    lines = build_transcript_lines(history, bot_name="Mika", max_lines=10, line_max_chars=240)
    block = build_transcript_block(lines)
    label1 = speaker_label_for_user_id("1")
    label2 = speaker_label_for_user_id("2")
    assert label1 != label2
    assert f"{label1}: hi" in block.text
    assert f"{label2}: yo" in block.text
    assert "Alex" not in block.text


def test_transcript_builder_participants_line_skips_bot_name():
    from mika_chat_core.utils.transcript_builder import build_participants_line
    from mika_chat_core.utils.speaker_labels import speaker_label_for_user_id

    u1 = speaker_label_for_user_id("1")
    u2 = speaker_label_for_user_id("2")
    lines = [
        f"[刚刚] {u1}: hi",
        "[刚刚] Mika: ok",
        f"[刚刚] {u2}: yo",
    ]
    out = build_participants_line(lines, bot_name="Mika", max_names=8, window_lines=60)
    assert u1 in out
    assert u2 in out
    assert "Mika" not in out
    assert f"last: {u2}" in out
