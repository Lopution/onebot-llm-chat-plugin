"""Media semantic helpers for context rendering.

Provide stable IDs/tokens for non-text content so history can preserve
"what kind of media happened here" even after textification.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Mapping


MEDIA_KIND_IMAGE = "image"
MEDIA_KIND_EMOJI = "emoji"


def normalize_media_kind(kind: Any) -> str:
    value = str(kind or "").strip().lower()
    if value in {MEDIA_KIND_EMOJI, "mface", "sticker"}:
        return MEDIA_KIND_EMOJI
    return MEDIA_KIND_IMAGE


def _stable_short_id(seed: str, *, length: int = 12) -> str:
    digest = hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()
    return digest[: max(6, int(length or 12))]


def build_media_semantic(
    *,
    kind: Any,
    asset_ref: Any = "",
    url: Any = "",
    emoji_id: Any = "",
    source: Any = "",
) -> Dict[str, str]:
    media_kind = normalize_media_kind(kind)
    ref = str(asset_ref or "").strip()
    resolved_url = str(url or "").strip()
    emoji = str(emoji_id or "").strip()
    src = str(source or "").strip()

    if media_kind == MEDIA_KIND_EMOJI:
        seed = emoji or ref or resolved_url
        if not seed:
            seed = "emoji:unknown"
        return {
            "kind": MEDIA_KIND_EMOJI,
            "id": _stable_short_id(f"emoji:{seed}"),
            "ref": ref or resolved_url or emoji,
            "source": src,
        }

    seed = resolved_url or ref
    if not seed:
        seed = "image:unknown"
    return {
        "kind": MEDIA_KIND_IMAGE,
        "id": _stable_short_id(f"image:{seed}"),
        "ref": ref or resolved_url,
        "source": src,
    }


def extract_media_semantic(part: Mapping[str, Any] | None, *, fallback_kind: Any = MEDIA_KIND_IMAGE) -> Dict[str, str]:
    if not isinstance(part, Mapping):
        return build_media_semantic(kind=fallback_kind)

    existing = part.get("mika_media")
    if isinstance(existing, Mapping):
        media_kind = normalize_media_kind(existing.get("kind") or fallback_kind)
        media_id = str(existing.get("id") or "").strip()
        media_ref = str(existing.get("ref") or "").strip()
        media_source = str(existing.get("source") or "").strip()
        if media_id:
            return {
                "kind": media_kind,
                "id": media_id,
                "ref": media_ref,
                "source": media_source,
            }

    image_url = part.get("image_url")
    if isinstance(image_url, Mapping):
        url = str(image_url.get("url") or "").strip()
    else:
        url = str(image_url or "").strip()

    return build_media_semantic(
        kind=(part.get("media_kind") or fallback_kind),
        asset_ref=part.get("asset_ref") or part.get("ref") or "",
        url=url,
        emoji_id=part.get("emoji_id") or "",
        source=part.get("source") or "",
    )


def placeholder_from_media_semantic(semantic: Mapping[str, Any] | None) -> str:
    media_id = ""
    media_kind = MEDIA_KIND_IMAGE
    if isinstance(semantic, Mapping):
        media_kind = normalize_media_kind(semantic.get("kind"))
        media_id = str(semantic.get("id") or "").strip()

    if media_kind == MEDIA_KIND_EMOJI:
        if media_id:
            return f"[表情][emoji:{media_id}]"
        return "[表情]"
    if media_id:
        return f"[图片][picid:{media_id}]"
    return "[图片]"


def placeholder_from_content_part(part: Mapping[str, Any] | None, *, fallback_kind: Any = MEDIA_KIND_IMAGE) -> str:
    return placeholder_from_media_semantic(extract_media_semantic(part, fallback_kind=fallback_kind))

