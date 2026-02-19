from __future__ import annotations

from mika_chat_core.utils.message_splitter import split_message_text


def test_split_message_text_returns_single_for_short_text():
    assert split_message_text("你好", max_length=100) == ["你好"]


def test_split_message_text_prefers_paragraph_boundary():
    text = "第一段很短。\n\n第二段也很短。"
    chunks = split_message_text(text, max_length=20)
    assert chunks == ["第一段很短。", "第二段也很短。"]


def test_split_message_text_falls_back_to_hard_split():
    text = "x" * 250
    chunks = split_message_text(text, max_length=80)
    assert len(chunks) == 4
    assert all(len(chunk) <= 80 for chunk in chunks)
