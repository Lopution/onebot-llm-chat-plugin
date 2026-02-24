"""Text splitting helpers for IM-friendly multi-message replies."""

from __future__ import annotations

import re
from typing import List

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;…])\s*")


def _hard_split(text: str, max_length: int) -> List[str]:
    content = str(text or "")
    if max_length <= 0 or len(content) <= max_length:
        return [content] if content else []
    chunks: List[str] = []
    start = 0
    while start < len(content):
        chunk = content[start : start + max_length].strip()
        if chunk:
            chunks.append(chunk)
        start += max_length
    return chunks


def split_message_text(text: str, *, max_length: int = 300) -> List[str]:
    """Split long text into readable chunks.

    Priority:
    1) Paragraphs (`\\n\\n`)
    2) Sentence boundaries
    3) Hard split
    """
    normalized = str(text or "").strip()
    if not normalized:
        return []
    max_len = max(60, int(max_length or 300))
    if len(normalized) <= max_len:
        if "\n\n" in normalized:
            paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
            if len(paragraphs) > 1:
                return paragraphs
        return [normalized]

    chunks: List[str] = []
    paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]

    for paragraph in paragraphs:
        if len(paragraph) <= max_len:
            chunks.append(paragraph)
            continue

        sentences = [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(paragraph) if part.strip()]
        if not sentences:
            chunks.extend(_hard_split(paragraph, max_len))
            continue

        buffer = ""
        for sentence in sentences:
            candidate = sentence if not buffer else f"{buffer}{sentence}"
            if len(candidate) <= max_len:
                buffer = candidate
                continue
            if buffer:
                chunks.append(buffer.strip())
            if len(sentence) <= max_len:
                buffer = sentence
            else:
                hard_parts = _hard_split(sentence, max_len)
                if hard_parts:
                    chunks.extend(hard_parts[:-1])
                    buffer = hard_parts[-1]
                else:
                    buffer = ""
        if buffer:
            chunks.append(buffer.strip())

    final_chunks = [chunk for chunk in chunks if chunk]
    if not final_chunks:
        return _hard_split(normalized, max_len)
    return final_chunks


__all__ = ["split_message_text"]
