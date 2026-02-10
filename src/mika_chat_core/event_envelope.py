"""Build host-agnostic event envelopes from best-effort host events."""

from __future__ import annotations

import time
from typing import Any, Iterable, List

from .contracts import Author, ContentPart, EventEnvelope
from .utils.event_context import build_event_context


def _segment_type(seg: Any) -> str:
    if isinstance(seg, dict):
        return str(seg.get("type") or "")
    return str(getattr(seg, "type", "") or "")


def _segment_data(seg: Any) -> dict:
    if isinstance(seg, dict):
        raw_data = seg.get("data", {})
    else:
        raw_data = getattr(seg, "data", {})
    return raw_data if isinstance(raw_data, dict) else {}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _extract_timestamp(event: Any) -> float:
    for attr in ("time", "timestamp"):
        if hasattr(event, attr):
            try:
                return float(getattr(event, attr))
            except Exception:
                continue
    return time.time()


def _extract_sender_role(event: Any) -> str:
    sender = getattr(event, "sender", None)
    if sender is None:
        return ""
    if isinstance(sender, dict):
        return _as_text(sender.get("role", "")).strip()
    return _as_text(getattr(sender, "role", "")).strip()


def _extract_asset_ref(data: dict) -> str:
    for key in ("url", "file", "file_id", "path"):
        value = _as_text(data.get(key, "")).strip()
        if value:
            return value
    return ""


def extract_content_parts(
    segments: Iterable[Any],
    *,
    fallback_plaintext: str = "",
) -> List[ContentPart]:
    """Convert host message segments to host-agnostic content parts."""
    parts: List[ContentPart] = []

    for seg in segments or []:
        seg_type = _segment_type(seg)
        data = _segment_data(seg)

        if seg_type == "text":
            text = _as_text(data.get("text", "")).strip()
            if text:
                parts.append(ContentPart(kind="text", text=text))
            continue

        if seg_type in {"at", "mention", "mention_all"}:
            if seg_type == "mention_all":
                parts.append(ContentPart(kind="mention", target_id="all", text="@全体成员"))
                continue
            target_id = _as_text(data.get("qq") or data.get("user_id") or data.get("target_id")).strip()
            mention_text = _as_text(data.get("text", "")).strip()
            if target_id == "all" and not mention_text:
                mention_text = "@全体成员"
            if target_id or mention_text:
                parts.append(
                    ContentPart(
                        kind="mention",
                        target_id=target_id,
                        text=mention_text or (f"@{target_id}" if target_id else ""),
                    )
                )
            continue

        if seg_type == "reply":
            target_id = _as_text(data.get("id") or data.get("message_id")).strip()
            if target_id:
                parts.append(ContentPart(kind="reply", target_id=target_id))
            continue

        if seg_type in {"image", "mface"}:
            asset_ref = _extract_asset_ref(data)
            parts.append(ContentPart(kind="image", asset_ref=asset_ref))
            continue

        if seg_type in {"file", "record", "video", "audio", "voice"}:
            asset_ref = _extract_asset_ref(data)
            parts.append(ContentPart(kind="attachment", asset_ref=asset_ref))
            continue

        # Best-effort fallback: if unknown segment still carries plain text.
        fallback_text = _as_text(data.get("text", "")).strip()
        if fallback_text:
            parts.append(ContentPart(kind="text", text=fallback_text))

    if not parts and fallback_plaintext.strip():
        parts.append(ContentPart(kind="text", text=fallback_plaintext.strip()))

    return parts


def build_event_envelope(
    bot: Any,
    event: Any,
    *,
    schema_version: int = 1,
    protocol: str = "onebot",
) -> EventEnvelope:
    """Build :class:`EventEnvelope` from host event with best-effort extraction."""
    ctx = build_event_context(bot, event)
    original_message = getattr(event, "original_message", None)
    message = original_message if original_message is not None else getattr(event, "message", None)
    parts = extract_content_parts(message or [], fallback_plaintext=ctx.plaintext or "")

    return EventEnvelope(
        schema_version=schema_version,
        session_id=ctx.session_key,
        platform=ctx.platform or "unknown",
        protocol=protocol,
        message_id=ctx.message_id or "",
        timestamp=_extract_timestamp(event),
        author=Author(
            id=ctx.user_id or "",
            nickname=ctx.sender_name or "",
            role=_extract_sender_role(event),
        ),
        content_parts=parts,
        meta={
            "is_group": ctx.is_group,
            "is_tome": ctx.is_tome,
            "group_id": ctx.group_id or "",
            "user_id": ctx.user_id or "",
        },
    )
