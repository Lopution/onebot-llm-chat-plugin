"""Group chat transcript builder (AstrBot-like working set).

Key idea:
- Storage can be very "full" (message_archive keeps everything).
- What we send to LLM must be a controlled working set (compact transcript).
"""

from __future__ import annotations

import json
import re
import time
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
_SPEAKER_TAG_RE = re.compile(r"^(?P<nick>.*)\((?P<uid>[^()]+)\)$")
_RENDERED_SPEAKER_RE = re.compile(r"^(?:\[[^\]]+\]\s+)?(?P<speaker>[^:]{1,80}):\s+")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _sanitize_display_name(name: str, *, max_chars: int = 24) -> str:
    cleaned = " ".join(str(name or "").split()).strip()
    if not cleaned:
        return ""
    # Keep it "name-like": drop high-noise punctuation while keeping CJK/ASCII letters/digits.
    cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\-_ ]", "", cleaned).strip()
    if not cleaned:
        return ""
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip()
    return cleaned


def _format_time_hint(ts: float, baseline_ts: float) -> str:
    """Return a short relative time hint like '[刚刚]' / '[3分钟前]'."""
    t = _safe_float(ts, 0.0)
    base = _safe_float(baseline_ts, 0.0)
    if t <= 0 or base <= 0:
        return ""
    if t > base:
        t = base
    delta = max(0.0, base - t)
    if delta < 60:
        return "[刚刚]"
    if delta < 3600:
        minutes = max(1, int(delta // 60))
        return f"[{minutes}分钟前]"
    if delta < 86400:
        hours = max(1, int(delta // 3600))
        return f"[{hours}小时前]"
    days = max(1, int(delta // 86400))
    return f"[{days}天前]"


def build_participants_line(
    lines: List[str],
    *,
    bot_name: str,
    max_names: int = 8,
    window_lines: int = 60,
) -> str:
    """Build a compact participants hint from already-rendered transcript lines."""
    resolved_bot = str(bot_name or "").strip()
    resolved_max = max(1, int(max_names or 8))
    window = max(1, int(window_lines or 60))

    active: List[str] = []
    seen: set[str] = set()
    last_speaker = ""

    tail = (lines or [])[-window:]
    for ln in reversed(tail):
        text = str(ln or "").strip()
        if not text:
            continue
        matched = _RENDERED_SPEAKER_RE.match(text)
        if not matched:
            continue
        speaker = (matched.group("speaker") or "").strip()
        if not speaker:
            continue
        if resolved_bot and (speaker == resolved_bot or speaker.startswith(f"{resolved_bot}(")):
            continue
        if not last_speaker:
            last_speaker = speaker
        if speaker in seen:
            continue
        seen.add(speaker)
        active.append(speaker)
        if len(active) >= resolved_max:
            break

    if not active:
        return ""
    active_str = ", ".join(active)
    if last_speaker:
        return f"[Participants] active: {active_str} | last: {last_speaker}"
    return f"[Participants] active: {active_str}"


def build_transcript_lines(
    history: List[Dict[str, Any]],
    *,
    bot_name: str,
    max_lines: int,
    line_max_chars: int,
) -> List[str]:
    if max_lines <= 0:
        return []

    # Only keep user/assistant messages; tool/system messages are not chatroom lines.
    normalized_history: List[Dict[str, Any]] = []
    for msg in history or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        if role in {"user", "assistant"}:
            normalized_history.append(msg)

    if not normalized_history:
        return []

    # Use the newest message timestamp as baseline so hints are deterministic
    # and do not depend on server locale/timezone.
    baseline_ts = 0.0
    for msg in reversed(normalized_history):
        baseline_ts = _safe_float(msg.get("timestamp"), 0.0)
        if baseline_ts > 0:
            break
    if baseline_ts <= 0:
        baseline_ts = _safe_float(time.time(), 0.0)

    # First pass: parse all lines, keep a stable display name for each user_id.
    entries: List[Dict[str, Any]] = []
    display_by_uid: Dict[str, str] = {}

    lines: List[str] = []
    for msg in normalized_history[-max_lines:]:
        role = str(msg.get("role") or "").strip().lower()
        content = render_transcript_content(msg.get("content"))
        content = _clip_line(content, max_chars=line_max_chars)
        if not content:
            continue

        # Keep stable msg_id anchors for media placeholders.
        msg_id = str(msg.get("message_id") or "").strip()
        if msg_id and "<msg_id:" not in content and ("[图片" in content or "[表情" in content):
            content = f"{content} <msg_id:{msg_id}>"

        ts = _safe_float(msg.get("timestamp"), 0.0)
        time_hint = _format_time_hint(ts, baseline_ts)

        if role == "assistant":
            matched = _SPEAKER_RE.match(content)
            speaker = ""
            said = ""
            if matched:
                speaker = (matched.group(1) or "").strip()
                said = (matched.group(2) or "").strip()
            speaker = _sanitize_display_name(speaker) or str(bot_name or "").strip() or "Assistant"
            said = said or content
            entries.append(
                {
                    "time_hint": time_hint,
                    "role": role,
                    "uid": "",
                    "speaker": speaker,
                    "said": said,
                }
            )
            continue

        matched = _SPEAKER_RE.match(content)
        speaker_raw = ""
        said = ""
        if matched:
            speaker_raw = (matched.group(1) or "").strip()
            said = (matched.group(2) or "").strip()
        said = said or content

        uid = str(msg.get("user_id") or "").strip()
        nick = ""
        if speaker_raw:
            tag_match = _SPEAKER_TAG_RE.match(speaker_raw)
            if tag_match:
                nick = (tag_match.group("nick") or "").strip()
                tag_uid = (tag_match.group("uid") or "").strip()
                if not uid and tag_uid:
                    uid = tag_uid
            else:
                nick = speaker_raw

        nick = _sanitize_display_name(nick, max_chars=24)
        if uid and nick:
            # Keep the newest nickname for each user_id (stable mapping).
            display_by_uid[uid] = nick

        entries.append(
            {
                "time_hint": time_hint,
                "role": role,
                "uid": uid,
                "speaker_raw": speaker_raw,
                "said": said,
            }
        )

    # Determine which display names collide; only then we append "(user_id)".
    name_counts: Dict[str, int] = {}
    for name in (display_by_uid or {}).values():
        if not name:
            continue
        name_counts[name] = name_counts.get(name, 0) + 1

    for ent in entries:
        role = str(ent.get("role") or "").strip().lower()
        time_hint = str(ent.get("time_hint") or "").strip()
        said = str(ent.get("said") or "").strip()
        if not said:
            continue

        prefix = f"{time_hint} " if time_hint else ""

        if role == "assistant":
            speaker = str(ent.get("speaker") or "").strip() or str(bot_name or "").strip() or "Assistant"
            lines.append(f"{prefix}{speaker}: {said}")
            continue

        uid = str(ent.get("uid") or "").strip()
        speaker_raw = str(ent.get("speaker_raw") or "").strip()
        speaker = ""
        if uid and uid in display_by_uid:
            speaker = display_by_uid[uid]
        if not speaker:
            # Fallback to raw tag or generic label.
            speaker = _sanitize_display_name(speaker_raw) or "User"

        if uid and speaker and name_counts.get(speaker, 0) > 1:
            speaker = f"{speaker}({uid})"

        lines.append(f"{prefix}{speaker}: {said}")

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
    "build_participants_line",
    "build_transcript_block",
    "shrink_transcript_block",
    "render_transcript_content",
]
