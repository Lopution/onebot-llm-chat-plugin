"""文档切片工具（RAG 基础）。"""

from __future__ import annotations

from typing import List


def _split_long_text(text: str, *, max_chars: int, overlap_chars: int) -> List[str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    chunks: List[str] = []
    step = max(1, max_chars - max(0, overlap_chars))
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + max_chars)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start += step
    return chunks


def split_text_chunks(
    text: str,
    *,
    max_chars: int = 450,
    overlap_chars: int = 80,
    min_chunk_chars: int = 10,
) -> List[str]:
    """将文本切片为 RAG 可检索块。"""
    max_chars = max(16, int(max_chars or 450))
    overlap_chars = max(0, min(int(overlap_chars or 0), max_chars // 2))
    min_chunk_chars = max(1, int(min_chunk_chars or 1))

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
    if not paragraphs:
        paragraphs = [normalized]
    else:
        filtered: List[str] = []
        seen_paragraphs = set()
        for paragraph in paragraphs:
            if len(paragraph) < min_chunk_chars:
                continue
            if paragraph in seen_paragraphs:
                continue
            seen_paragraphs.add(paragraph)
            filtered.append(paragraph)
        paragraphs = filtered

    chunks: List[str] = []
    buffer = ""

    def _flush() -> None:
        nonlocal buffer
        value = buffer.strip()
        if value:
            chunks.extend(_split_long_text(value, max_chars=max_chars, overlap_chars=overlap_chars))
        buffer = ""

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            _flush()
            chunks.extend(_split_long_text(paragraph, max_chars=max_chars, overlap_chars=overlap_chars))
            continue

        candidate = paragraph if not buffer else f"{buffer}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            _flush()
            buffer = paragraph

    _flush()

    deduped: List[str] = []
    seen = set()
    for chunk in chunks:
        value = chunk.strip()
        if len(value) < min_chunk_chars:
            continue
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
