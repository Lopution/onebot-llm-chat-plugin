"""Message parsing helpers extracted from handlers.py."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from .contracts import ContentPart, EventEnvelope
from .infra.logging import logger as log
from .ports.bot_api import PlatformApiPort
from .utils.media_semantics import placeholder_from_media_semantic
from .utils.event_context import build_event_context_from_envelope
from .utils.recent_images import get_image_cache


def _extract_sender_from_message_data(msg_data: dict[str, Any]) -> tuple[str, str]:
    sender = msg_data.get("sender", {})
    if isinstance(sender, dict):
        sender_name = str(sender.get("card") or sender.get("nickname") or "").strip()
        sender_id = str(sender.get("user_id", "") or "").strip()
    else:
        sender_name = ""
        sender_id = ""
    sender_name = sender_name or str(msg_data.get("nickname") or msg_data.get("author_name") or "某人")
    sender_id = sender_id or str(msg_data.get("user_id") or msg_data.get("author_id") or "")
    return sender_name, sender_id


def _iter_message_segment_dicts(message: Any) -> list[dict[str, Any]]:
    if not isinstance(message, list):
        return []
    results: list[dict[str, Any]] = []
    for item in message:
        if isinstance(item, dict):
            results.append(item)
        else:
            seg_type = getattr(item, "type", None)
            seg_data = getattr(item, "data", {}) or {}
            results.append({"type": seg_type, "data": seg_data})
    return results


def _render_quoted_text_from_message_data(message_data: Any) -> str:
    if isinstance(message_data, str):
        return message_data.strip()
    pieces: list[str] = []
    for seg in _iter_message_segment_dicts(message_data):
        seg_type = str(seg.get("type") or "")
        seg_data = seg.get("data") or {}
        if not isinstance(seg_data, dict):
            seg_data = {}
        if seg_type == "text":
            text = str(seg_data.get("text") or "").strip()
            if text:
                pieces.append(text)
        elif seg_type == "image":
            pieces.append("[图片]")
        elif seg_type == "mface":
            pieces.append("[表情]")
        elif seg_type in {"at", "mention"}:
            target = str(seg_data.get("qq") or seg_data.get("user_id") or seg_data.get("target_id") or "").strip()
            pieces.append(f"@{target}" if target else "@某人")
        elif seg_type == "record":
            pieces.append("[语音]")
        elif seg_type == "video":
            pieces.append("[视频]")
        elif seg_type == "file":
            pieces.append("[文件]")
        elif seg_type == "forward":
            pieces.append("[转发消息]")
    return "".join(pieces).strip()


async def parse_envelope_with_mentions(
    *,
    envelope: EventEnvelope,
    platform_api: Optional[PlatformApiPort],
    max_images: int,
    quote_image_caption_enabled: bool,
    quote_image_caption_prompt: str,
    quote_image_caption_timeout_seconds: float,
    resolve_image_urls_via_port: Callable[..., Awaitable[list[str]]],
) -> tuple[str, list[str]]:
    """解析 EventEnvelope 并保留 @ 与引用语义。"""
    ctx = build_event_context_from_envelope(envelope)
    image_cache = get_image_cache()
    text_parts: list[str] = []
    extra_images: list[str] = []
    quoted_content: Optional[str] = None

    group_id_str = str(ctx.group_id or "").strip()
    for part in envelope.content_parts:
        if part.kind == "text":
            text_parts.append(str(part.text or ""))
            continue

        if part.kind == "mention":
            mention_target = str(part.target_id or "").strip()
            if mention_target == "all":
                text_parts.append(" @全体成员 ")
                continue
            if mention_target and mention_target == str(envelope.bot_self_id or "").strip():
                text_parts.append(" @Mika ")
                continue
            nickname = ""
            if mention_target and group_id_str and platform_api is not None:
                try:
                    member_info = await platform_api.get_member_info(
                        conversation_id=group_id_str,
                        user_id=mention_target,
                    )
                    if isinstance(member_info, dict):
                        nickname = str(member_info.get("card") or member_info.get("nickname") or "").strip()
                except Exception:
                    nickname = ""
            text_parts.append(f" @{nickname or mention_target or '某人'} ")
            continue

        if part.kind == "reply":
            reply_msg_id = str(part.target_id or "").strip()
            if not reply_msg_id:
                continue

            cached_images, cache_hit = image_cache.get_images_by_message_id(
                group_id=group_id_str,
                user_id=str(ctx.user_id),
                message_id=reply_msg_id,
            )
            if cache_hit and cached_images:
                extra_images.extend([img.url for img in cached_images if img.url])
                sender_name = cached_images[0].sender_name if cached_images else "某人"
                quoted_content = f"[引用 {sender_name} 的消息: [图片×{len(cached_images)}]]"
                continue

            timeout_seconds = max(0.5, float(quote_image_caption_timeout_seconds or 3.0))
            msg_data: Optional[dict[str, Any]] = None
            if platform_api is not None:
                try:
                    fetched = await asyncio.wait_for(
                        platform_api.fetch_message(message_id=reply_msg_id),
                        timeout=timeout_seconds,
                    )
                    if isinstance(fetched, dict):
                        msg_data = fetched
                except asyncio.TimeoutError:
                    log.warning(
                        f"[Reply处理] 获取引用消息超时(fetch_message) | msg_id={reply_msg_id} | timeout={timeout_seconds:.1f}s"
                    )
                except Exception as exc:
                    log.warning(f"[Reply处理] 获取引用消息失败(fetch_message) | msg_id={reply_msg_id} | error={exc}")

            if not isinstance(msg_data, dict):
                continue

            sender_name, sender_id = _extract_sender_from_message_data(msg_data)
            raw_message = msg_data.get("message", "")
            quoted_text = _render_quoted_text_from_message_data(raw_message)

            raw_parts = msg_data.get("content_parts", [])
            message_parts = []
            if isinstance(raw_parts, list):
                try:
                    message_parts = [ContentPart.from_dict(dict(item or {})) for item in raw_parts]
                except Exception:
                    message_parts = []
            resolved_quote_images = await resolve_image_urls_via_port(
                message_parts,
                platform_api=platform_api,
                max_images=max_images,
            )

            if resolved_quote_images:
                for img_url in resolved_quote_images:
                    if img_url not in extra_images:
                        extra_images.append(img_url)
                image_cache.cache_images(
                    group_id=group_id_str,
                    user_id=sender_id,
                    image_urls=resolved_quote_images,
                    sender_name=sender_name,
                    message_id=reply_msg_id,
                )
                if quote_image_caption_enabled:
                    try:
                        caption_text = str(quote_image_caption_prompt).format(
                            count=len(resolved_quote_images),
                            sender=sender_name,
                        )
                    except Exception:
                        caption_text = f"[引用图片共{len(resolved_quote_images)}张]"
                    quoted_text = f"{quoted_text}{caption_text}".strip()

            if quoted_text or extra_images:
                quoted_content = f"[引用 {sender_name} 的消息: {quoted_text or '[多媒体内容]'}]"
            continue

        if part.kind == "image":
            media = part.meta.get("mika_media") if isinstance(part.meta, dict) else None
            text_parts.append(placeholder_from_media_semantic(media))

    result = "".join(text_parts).strip()
    if quoted_content:
        result = f"{quoted_content}\n{result}"
    return result, extra_images
