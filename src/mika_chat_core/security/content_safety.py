"""Outbound content safety filter."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_BLOCK_KEYWORDS: tuple[str, ...] = (
    "自杀教程",
    "制作炸弹",
    "恐怖袭击",
    "儿童色情",
)


@dataclass(frozen=True)
class ContentSafetyResult:
    text: str
    filtered: bool
    action: str
    hits: list[str]


def apply_content_safety_filter(
    text: str,
    *,
    enabled: bool,
    action: str,
    block_keywords: list[str] | None,
    replacement: str,
) -> ContentSafetyResult:
    raw = str(text or "")
    mode = str(action or "replace").strip().lower()
    if mode not in {"replace", "drop"}:
        mode = "replace"

    if not enabled or not raw.strip():
        return ContentSafetyResult(text=raw, filtered=False, action=mode, hits=[])

    candidates = [str(item or "").strip() for item in (block_keywords or []) if str(item or "").strip()]
    if not candidates:
        candidates = list(DEFAULT_BLOCK_KEYWORDS)

    haystack = raw.lower()
    hits = [item for item in candidates if item.lower() in haystack]
    if not hits:
        return ContentSafetyResult(text=raw, filtered=False, action=mode, hits=[])

    if mode == "drop":
        return ContentSafetyResult(text="", filtered=True, action="drop", hits=hits)

    safe_text = str(replacement or "").strip() or "抱歉，这条回复不适合直接发送。"
    return ContentSafetyResult(
        text=safe_text,
        filtered=True,
        action="replace",
        hits=hits,
    )

