"""Group chat transcript builder (AstrBot-like working set).

Key idea:
- Storage can be very "full" (message_archive keeps everything).
- What we send to LLM must be a controlled working set (compact transcript).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .context_schema import normalize_content
from .media_semantics import placeholder_from_content_part


TRANSCRIPT_HEADER = "[Chatroom Transcript]"
TRANSCRIPT_FOOTER = "[End Transcript]"


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    lines_used: int
    chars_used: int


def _parse_archive_content(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text:
        return ""
    if text[:1] not in {"[", "{"}:
        return raw
    try:
        return json.loads(text)
    except Exception:
        return raw


def render_transcript_content(content: Any) -> str:
    parsed = _parse_archive_content(content)
    normalized = normalize_content(parsed)
    if isinstance(normalized, str):
        return " ".join(str(normalized or "").split())
    if isinstance(normalized, list):
        parts: List[str] = []
        for item in normalized:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").lower()
            if item_type == "text":
                parts.append(str(item.get("text") or ""))
            elif item_type == "image_url":
                parts.append(placeholder_from_content_part(item))
        return " ".join(p for p in parts if p).strip()
    return " ".join(str(parsed or "").split())


def _clip_line(text: str, *, max_chars: int) -> str:
    resolved_max = max(40, int(max_chars or 240))
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= resolved_max:
        return cleaned
    return cleaned[: resolved_max - 1].rstrip() + "…"


_SPEAKER_RE = re.compile(r"^\[(.*?)\]:\s*(.*)$")


def build_transcript_lines(
    history: List[Dict[str, Any]],
    *,
    bot_name: str,
    max_lines: int,
    line_max_chars: int,
) -> List[str]:
    if max_lines <= 0:
        return []

    lines: List[str] = []
    for msg in (history or [])[-max_lines:]:
        role = str(msg.get("role") or "").strip().lower()
        content = render_transcript_content(msg.get("content"))
        content = _clip_line(content, max_chars=line_max_chars)
        if not content:
            continue

        # Keep stable msg_id anchors for media placeholders.
        msg_id = str(msg.get("message_id") or "").strip()
        if msg_id and "<msg_id:" not in content and ("[图片" in content or "[表情" in content):
            content = f"{content} <msg_id:{msg_id}>"

        if role == "assistant":
            lines.append(f"{bot_name}: {content}")
            continue

        matched = _SPEAKER_RE.match(content)
        if matched:
            speaker = (matched.group(1) or "").strip()
            said = (matched.group(2) or "").strip()
            if speaker and said:
                lines.append(f"{speaker}: {said}")
                continue

        lines.append(content)

    return lines


def build_transcript_block(lines: List[str]) -> TranscriptResult:
    cleaned_lines = [str(x or "").strip() for x in (lines or []) if str(x or "").strip()]
    if not cleaned_lines:
        text = f"{TRANSCRIPT_HEADER}\n(无最近记录)\n{TRANSCRIPT_FOOTER}"
        return TranscriptResult(text=text, lines_used=0, chars_used=len(text))

    body = "\n".join(cleaned_lines).strip()
    text = f"{TRANSCRIPT_HEADER}\n{body}\n{TRANSCRIPT_FOOTER}"
    return TranscriptResult(text=text, lines_used=len(cleaned_lines), chars_used=len(text))


def shrink_transcript_block(text: str, *, keep_ratio: float) -> TranscriptResult:
    """Shrink an existing transcript block by dropping oldest lines."""
    raw = str(text or "")
    if TRANSCRIPT_HEADER not in raw or TRANSCRIPT_FOOTER not in raw:
        return TranscriptResult(text=raw, lines_used=0, chars_used=len(raw))

    # Extract lines between markers.
    try:
        start = raw.index(TRANSCRIPT_HEADER) + len(TRANSCRIPT_HEADER)
        end = raw.index(TRANSCRIPT_FOOTER)
    except ValueError:
        return TranscriptResult(text=raw, lines_used=0, chars_used=len(raw))

    middle = raw[start:end].strip("\n").strip()
    lines = [ln.strip() for ln in middle.splitlines() if ln.strip()]
    if not lines:
        return TranscriptResult(
            text=f"{TRANSCRIPT_HEADER}\n(无最近记录)\n{TRANSCRIPT_FOOTER}",
            lines_used=0,
            chars_used=len(raw),
        )

    ratio = float(keep_ratio)
    ratio = max(0.1, min(1.0, ratio))
    keep = max(1, int(len(lines) * ratio))
    kept_lines = lines[-keep:]
    return build_transcript_block(kept_lines)


__all__ = [
    "TRANSCRIPT_HEADER",
    "TRANSCRIPT_FOOTER",
    "TranscriptResult",
    "build_transcript_lines",
    "build_transcript_block",
    "shrink_transcript_block",
    "render_transcript_content",
]
