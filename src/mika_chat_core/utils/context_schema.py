"""上下文消息结构定义与兼容转换工具。"""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict, Union

from .media_semantics import (
    build_media_semantic,
    extract_media_semantic,
    placeholder_from_content_part,
)


class ImageURL(TypedDict, total=False):
    url: str


class MediaSemantic(TypedDict, total=False):
    kind: str
    id: str
    ref: str
    source: str


class ContentPart(TypedDict, total=False):
    type: str
    text: str
    image_url: ImageURL
    mika_media: MediaSemantic


class ContextMessage(TypedDict, total=False):
    role: str
    content: Union[str, List[ContentPart]]
    message_id: str
    timestamp: float
    tool_calls: List[Dict[str, Any]]
    tool_call_id: str


def _normalize_part(part: Any) -> ContentPart | None:
    if not isinstance(part, dict):
        return None

    part_type = str(part.get("type") or "").strip().lower()
    if part_type == "text":
        return {"type": "text", "text": str(part.get("text") or "")}

    if part_type == "image_url":
        semantic = extract_media_semantic(part, fallback_kind=part.get("media_kind") or "image")
        image_url = part.get("image_url")
        if isinstance(image_url, dict):
            url = str(image_url.get("url") or "").strip()
        else:
            url = str(image_url or "").strip()
        if not url:
            return {"type": "text", "text": placeholder_from_content_part(part)}
        return {"type": "image_url", "image_url": {"url": url}, "mika_media": semantic}

    if part_type in {"image", "mface", "emoji"}:
        data = part.get("data") if isinstance(part.get("data"), dict) else {}
        url = str((data or {}).get("url") or (data or {}).get("file") or "").strip()
        semantic = build_media_semantic(
            kind=part.get("media_kind") or part_type,
            asset_ref=(data or {}).get("file_id") or (data or {}).get("file") or "",
            url=url,
            emoji_id=(data or {}).get("emoji_id") or (data or {}).get("id") or "",
            source=(data or {}).get("source") or part_type,
        )
        if url:
            return {"type": "image_url", "image_url": {"url": url}, "mika_media": semantic}
        return {"type": "text", "text": placeholder_from_content_part({"mika_media": semantic})}

    text = str(part.get("text") or part.get("content") or "").strip()
    if text:
        return {"type": "text", "text": text}
    return None


def normalize_content(content: Any) -> Union[str, List[ContentPart]]:
    """将历史 content 归一化为字符串或标准多模态 part 列表。"""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        normalized: List[ContentPart] = []
        for part in content:
            parsed = _normalize_part(part)
            if parsed is not None:
                normalized.append(parsed)
        if normalized:
            return normalized
        return ""

    if isinstance(content, dict):
        parsed = _normalize_part(content)
        if parsed is not None:
            return [parsed]
        return ""

    return str(content or "")


def normalize_context_message(raw: Any) -> ContextMessage | None:
    """归一化单条上下文消息。"""
    if not isinstance(raw, dict):
        return None

    role = str(raw.get("role") or "").strip().lower()
    if role not in {"system", "user", "assistant", "tool"}:
        return None

    message: ContextMessage = {"role": role, "content": normalize_content(raw.get("content", ""))}

    message_id = raw.get("message_id")
    if message_id is not None and str(message_id).strip():
        message["message_id"] = str(message_id)

    timestamp = raw.get("timestamp")
    if timestamp is not None:
        try:
            message["timestamp"] = float(timestamp)
        except (TypeError, ValueError):
            pass

    tool_calls = raw.get("tool_calls")
    if role == "assistant" and isinstance(tool_calls, list):
        message["tool_calls"] = tool_calls

    tool_call_id = raw.get("tool_call_id")
    if role == "tool" and tool_call_id is not None and str(tool_call_id).strip():
        message["tool_call_id"] = str(tool_call_id)

    return message


def normalize_context_messages(raw_messages: Any) -> List[ContextMessage]:
    """归一化上下文消息列表（兼容旧格式）。"""
    if not isinstance(raw_messages, list):
        return []

    normalized: List[ContextMessage] = []
    for raw in raw_messages:
        parsed = normalize_context_message(raw)
        if parsed is not None:
            normalized.append(parsed)
    return normalized


def estimate_text_tokens(text: str) -> int:
    """粗略估算 token 数。"""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_message_tokens(message: ContextMessage) -> int:
    """估算单条消息 token 数（用于软上限裁剪）。"""
    total = 4
    content = message.get("content", "")
    if isinstance(content, str):
        total += estimate_text_tokens(content)
    elif isinstance(content, list):
        for part in content:
            part_type = str(part.get("type") or "").lower()
            if part_type == "text":
                total += estimate_text_tokens(str(part.get("text") or ""))
            elif part_type == "image_url":
                total += 16
            else:
                total += 4

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for item in tool_calls:
            if isinstance(item, dict):
                total += estimate_text_tokens(str(item))

    if message.get("tool_call_id"):
        total += 4

    return total
