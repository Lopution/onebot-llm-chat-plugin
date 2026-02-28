"""Speaker label helpers (MaiBot-style).

Goal
- Avoid leaking raw platform nicknames into LLM-facing prompts, because nicknames can
  contain topic-like tokens (e.g. "Q12/Q7") and the model may treat them as user text.
- Keep storage format unchanged (we still store "[nickname(user_id)]: ..." for legacy
  context_store parsing), but render LLM-visible text using stable, safe aliases.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional


SPEAKER_LABEL_PREFIX = "U"
SPEAKER_LABEL_HEX_LEN = 6

_TAGGED_MESSAGE_RE = re.compile(r"^\[(?P<tag>[^\]]+)\]:\s*(?P<body>.*)$", re.DOTALL)
_TAG_WITH_UID_RE = re.compile(r"^(?P<nick>.+?)\((?P<uid>[^()]{1,64})\)$")


@dataclass(frozen=True)
class ParsedSpeakerMessage:
    """Parsed result for messages like "[nickname(user_id)]: body"."""

    tag: str
    uid: str
    body: str


def speaker_label_for_user_id(user_id: str) -> str:
    """Return a stable, prompt-safe speaker label for a platform user_id."""
    uid = str(user_id or "").strip()
    if not uid:
        return "User"
    digest = hashlib.sha256(uid.encode("utf-8")).hexdigest()
    suffix = digest[:SPEAKER_LABEL_HEX_LEN]
    return f"{SPEAKER_LABEL_PREFIX}{suffix}"


def parse_speaker_tagged_message(message: str) -> Optional[ParsedSpeakerMessage]:
    """Parse a string in the form "[tag]: body" and extract uid when tag is "nick(uid)"."""
    raw = str(message or "")
    matched = _TAGGED_MESSAGE_RE.match(raw)
    if not matched:
        return None

    tag = str(matched.group("tag") or "").strip()
    body = str(matched.group("body") or "")

    uid = ""
    tag_uid = _TAG_WITH_UID_RE.match(tag)
    if tag_uid:
        uid = str(tag_uid.group("uid") or "").strip()

    return ParsedSpeakerMessage(tag=tag, uid=uid, body=body)


def build_llm_safe_message_text(message: str) -> str:
    """Build the LLM-facing version of an incoming message.

    - Only rewrites group-formatted messages: "[nickname(user_id)]: body" -> "Uxxxxxx: body"
    - Leaves private tags like "[⭐Sensei]: ..." untouched.
    """
    parsed = parse_speaker_tagged_message(message)
    if parsed is None:
        return str(message or "")
    if not parsed.uid:
        return str(message or "")

    body = str(parsed.body or "").strip()
    if not body:
        return speaker_label_for_user_id(parsed.uid)
    return f"{speaker_label_for_user_id(parsed.uid)}: {body}"


__all__ = [
    "ParsedSpeakerMessage",
    "build_llm_safe_message_text",
    "parse_speaker_tagged_message",
    "speaker_label_for_user_id",
]

