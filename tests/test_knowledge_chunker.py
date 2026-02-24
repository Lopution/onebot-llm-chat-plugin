from __future__ import annotations

from mika_chat_core.utils.knowledge_chunker import split_text_chunks


def test_split_text_chunks_basic():
    text = "第一段内容。\n\n第二段内容稍微长一点，用于测试切片逻辑。\n\n第三段。"
    chunks = split_text_chunks(text, max_chars=24, overlap_chars=4, min_chunk_chars=2)
    assert chunks
    assert all(len(item) <= 24 for item in chunks)


def test_split_text_chunks_dedup_and_min_len():
    text = "a\n\nab\n\n这是有效内容\n\n这是有效内容"
    chunks = split_text_chunks(text, max_chars=64, overlap_chars=8, min_chunk_chars=3)
    assert chunks == ["这是有效内容"]
