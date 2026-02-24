"""Protocol-semantic transcript helpers for Stage B.

This module keeps host/protocol normalization in core and lets adapters reuse
the same rules when turning message semantics into compact text transcripts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from .contracts import ContentPart, EventEnvelope
from .utils.media_semantics import (
    MEDIA_KIND_EMOJI,
    normalize_media_kind,
    placeholder_from_media_semantic,
)


@dataclass(frozen=True)
class SemanticSummary:
    has_reply: bool
    has_mention: bool
    mention_tokens: List[str]
    image_count: int
    emoji_count: int
    image_placeholders: List[str]
    attachment_count: int


def _mention_token(part: ContentPart) -> str:
    target = (part.target_id or "").strip()
    text = (part.text or "").strip()
    if text:
        return text if text.startswith("@") else f"@{text}"
    if target == "all":
        return "@全体成员"
    if target:
        return f"@{target}"
    return "@someone"


def summarize_content_parts(parts: Iterable[ContentPart]) -> SemanticSummary:
    has_reply = False
    mention_tokens: List[str] = []
    image_count = 0
    emoji_count = 0
    image_placeholders: List[str] = []
    attachment_count = 0

    for part in parts or []:
        if part.kind == "reply":
            has_reply = True
        elif part.kind == "mention":
            mention_tokens.append(_mention_token(part))
        elif part.kind == "image":
            image_count += 1
            media = part.meta.get("mika_media") if isinstance(part.meta, dict) else None
            media_kind = normalize_media_kind(
                (media or {}).get("kind") if isinstance(media, dict) else part.meta.get("media_kind", "")
            )
            if media_kind == MEDIA_KIND_EMOJI:
                emoji_count += 1

            # 仅当有显式媒体语义时输出稳定 token；否则保持旧占位行为。
            if isinstance(media, dict) and media:
                image_placeholders.append(placeholder_from_media_semantic(media))
        elif part.kind == "attachment":
            attachment_count += 1

    return SemanticSummary(
        has_reply=has_reply,
        has_mention=bool(mention_tokens),
        mention_tokens=mention_tokens,
        image_count=image_count,
        emoji_count=emoji_count,
        image_placeholders=image_placeholders,
        attachment_count=attachment_count,
    )


def summarize_envelope(envelope: EventEnvelope) -> SemanticSummary:
    return summarize_content_parts(envelope.content_parts)


def build_context_record_text(
    *,
    summary: SemanticSummary,
    plaintext: str,
    parsed_text: str = "",
    parse_failed: bool = False,
) -> str:
    """Build stable transcript text for context persistence.

    Rules:
    - Prefer parsed text when available.
    - For parse failures on reply/mention, fallback to semantic placeholders.
    - Always append image/attachment placeholders for current message assets.
    """
    text = (parsed_text or "").strip()
    if not text:
        if parse_failed and (summary.has_reply or summary.has_mention):
            pieces: List[str] = []
            if summary.has_reply:
                pieces.append("[引用消息]")
            if summary.mention_tokens:
                pieces.append(" ".join(summary.mention_tokens))
            plain = (plaintext or "").strip()
            if plain:
                pieces.append(plain)
            text = " ".join(x for x in pieces if x).strip()
        else:
            text = (plaintext or "").strip()

    if summary.image_count > 0:
        if summary.image_placeholders:
            image_placeholder = " ".join(summary.image_placeholders)
        else:
            image_placeholder = "[图片]" if summary.image_count == 1 else f"[图片×{summary.image_count}]"
        text = f"{text} {image_placeholder}".strip() if text else image_placeholder

    if summary.attachment_count > 0:
        attachment_placeholder = "[附件]" if summary.attachment_count == 1 else f"[附件×{summary.attachment_count}]"
        text = f"{text} {attachment_placeholder}".strip() if text else attachment_placeholder

    return text
