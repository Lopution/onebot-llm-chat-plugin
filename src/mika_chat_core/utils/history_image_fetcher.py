"""History image fetching helpers.

This module is shared by:
- the `fetch_history_images` tool
- the TWO_STAGE auto-attach flow in handlers

It avoids importing `mika_chat_core.tools` to prevent circular imports.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..infra.logging import logger as log


def _normalize_context_key(context_key: Any) -> str:
    value = str(context_key or "").strip()
    return value


def _split_context_key(context_key: str) -> tuple[Optional[str], Optional[str]]:
    """Return (group_id, user_id) for cache lookup."""
    key = _normalize_context_key(context_key)
    if key.startswith("group:"):
        gid = key.split(":", 1)[1].strip()
        return (gid or None), None
    if key.startswith("private:"):
        uid = key.split(":", 1)[1].strip()
        return None, (uid or None)
    return None, None


def _extract_archive_image_urls(normalized: Any) -> list[str]:
    if not isinstance(normalized, list):
        return []
    urls: list[str] = []
    for part in normalized:
        if not isinstance(part, dict):
            continue
        if str(part.get("type") or "").lower() != "image_url":
            continue
        image_url = part.get("image_url")
        if isinstance(image_url, dict):
            url = str(image_url.get("url") or "").strip()
        else:
            url = str(image_url or "").strip()
        if url:
            urls.append(url)
    return urls


async def fetch_history_images_data_urls(
    *,
    context_key: str,
    msg_ids: list[str],
    max_images: int,
    plugin_config: Any,
    get_db_fn: Optional[Callable[[], Awaitable[Any]]] = None,
    get_image_cache_fn: Optional[Callable[[], Any]] = None,
    get_image_processor_fn: Optional[Callable[[], Any]] = None,
    normalize_content_fn: Optional[Callable[[Any], Any]] = None,
    metrics_obj: Optional[Any] = None,
) -> list[dict[str, str]]:
    """Fetch images for msg_ids within a context key and return data URLs.

    Returns a list of:
    - msg_id
    - sender_name (best-effort)
    - data_url (data:<mime>;base64,<payload>)
    """

    context_key_str = _normalize_context_key(context_key)
    if not context_key_str:
        return []

    max_images_value = max(0, int(max_images or 0))
    if max_images_value <= 0:
        return []

    max_allowed = int(getattr(plugin_config, "mika_history_image_two_stage_max", max_images_value) or max_images_value)
    max_allowed = max(1, max_allowed)
    max_images_value = min(max_images_value, max_allowed)

    normalized_msg_ids: list[str] = []
    for raw_id in msg_ids or []:
        mid = str(raw_id or "").strip()
        if not mid:
            continue
        if mid in normalized_msg_ids:
            continue
        normalized_msg_ids.append(mid)
        if len(normalized_msg_ids) >= max_images_value:
            break
    if not normalized_msg_ids:
        return []

    if get_db_fn is None:
        from .context_db import get_db as get_db_fn  # type: ignore[assignment]
    if get_image_cache_fn is None:
        from .recent_images import get_image_cache as get_image_cache_fn  # type: ignore[assignment]
    if get_image_processor_fn is None:
        from .image_processor import get_image_processor as get_image_processor_fn  # type: ignore[assignment]
    if normalize_content_fn is None:
        from .context_schema import normalize_content as normalize_content_fn  # type: ignore[assignment]

    group_id, user_id = _split_context_key(context_key_str)
    cache_group_id = group_id
    cache_user_id = user_id or ""
    if cache_group_id:
        cache_user_id = ""

    image_cache = get_image_cache_fn()
    processor = get_image_processor_fn()
    result_images: list[dict[str, str]] = []

    async def _append_data_url(
        *,
        msg_id: str,
        sender_name: str,
        image_url: str,
        source: str,
    ) -> None:
        if len(result_images) >= max_images_value:
            return
        try:
            base64_data, mime_type = await processor.download_and_encode(image_url)
            result_images.append(
                {
                    "msg_id": msg_id,
                    "sender_name": str(sender_name or "").strip() or "某人",
                    "data_url": f"data:{mime_type};base64,{base64_data}",
                }
            )
            if metrics_obj is not None:
                if source == "cache":
                    metrics_obj.history_image_fetch_tool_source_cache_total += 1
                elif source == "archive":
                    metrics_obj.history_image_fetch_tool_source_archive_total += 1
                elif source == "get_msg":
                    metrics_obj.history_image_fetch_tool_source_get_msg_total += 1
        except Exception as exc:
            log.warning(
                f"history_image_fetcher: 下载图片失败 | msg_id={msg_id} | source={source} | error={exc}"
            )

    for msg_id in normalized_msg_ids:
        if len(result_images) >= max_images_value:
            break

        cached_images, found = image_cache.get_images_by_message_id(
            group_id=cache_group_id,
            user_id=cache_user_id,
            message_id=str(msg_id),
        )
        if found and cached_images:
            for img in cached_images:
                if len(result_images) >= max_images_value:
                    break
                await _append_data_url(
                    msg_id=str(msg_id),
                    sender_name=str(getattr(img, "sender_name", "") or "某人"),
                    image_url=str(getattr(img, "url", "") or ""),
                    source="cache",
                )
            if len(result_images) >= max_images_value:
                continue

        try:
            db = await get_db_fn()
            async with db.execute(
                """
                SELECT content, user_id
                FROM message_archive
                WHERE context_key = ? AND message_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (context_key_str, str(msg_id)),
            ) as cursor:
                row = await cursor.fetchone()
        except Exception as exc:
            log.warning(f"history_image_fetcher: archive 回查失败 | msg_id={msg_id} | error={exc}")
            row = None

        if not row or not row[0]:
            continue

        raw_content = row[0]
        archive_sender = str(row[1] or "").strip() if len(row) > 1 else ""

        parsed_content: Any = raw_content
        if isinstance(raw_content, str):
            try:
                parsed_content = json.loads(raw_content)
            except Exception:
                parsed_content = raw_content

        normalized = normalize_content_fn(parsed_content)
        archive_urls = _extract_archive_image_urls(normalized)
        for img_url in archive_urls:
            if len(result_images) >= max_images_value:
                break
            await _append_data_url(
                msg_id=str(msg_id),
                sender_name=archive_sender or "某人",
                image_url=img_url,
                source="archive",
            )

    return result_images

