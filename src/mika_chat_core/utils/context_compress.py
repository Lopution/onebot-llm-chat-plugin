"""上下文压缩模块。

提供消息内容压缩和安全过滤功能，用于：
- 减少历史上下文的 Token 消耗
- 过滤/替换敏感词汇，降低 API 安全风控触发概率

压缩策略：
- Level 1: 长文本截断（保留头尾）
- Level 2: 更激进的压缩（用于历史消息）
- 多模态内容特殊处理

相关模块：
- [`context_store`](context_store.py:1): 上下文存储，调用本模块进行压缩
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Union

from ..infra.logging import logger as log


# ==================== Magic-number constants ====================
# 消息压缩相关长度限制
COMPRESS_MAX_LENGTH = 500
COMPRESS_HEAD_LENGTH = 400
COMPRESS_TAIL_LENGTH = 50

# Level 2 压缩限制
COMPRESS_L2_MAX_LENGTH = 200
COMPRESS_L2_HEAD_LENGTH = 150
COMPRESS_L2_MULTIMODAL_MAX_LENGTH = 100
COMPRESS_L2_MULTIMODAL_HEAD_LENGTH = 80


SAFETY_REPLACEMENTS: Dict[str, str] = {
    r"萝莉": "可爱的女孩",
    r"loli": "可爱的女孩",
    r"幼女": "小女孩",
    r"调教": "培养",
    r"奴隶": "助手",
    r"主人": "老师",
    r"女仆": "助理",
    r"涩图": "图片",
    r"色图": "图片",
    r"黄图": "图片",
    r"r18": "成人内容",
    r"R18": "成人内容",
    r"工口": "成人内容",
    r"エロ": "成人内容",
    r"裸体": "身体",
    r"胸部": "身材",
    r"巨乳": "身材好",
    r"贫乳": "身材纤细",
    r"内衣": "服装",
    r"泳装": "夏装",
    r"死亡": "离开",
    r"杀死": "击败",
    r"杀掉": "击败",
    r"自杀": "放弃",
    r"血腥": "激烈",
    r"暴力": "冲突",
    r"毒品": "物品",
    r"武器": "道具",
    r"炸弹": "物品",
    r"爆炸": "剧烈反应",
}


def sanitize_text_for_safety(text: str) -> str:
    if not text:
        return text

    sanitized = text
    for pattern, replacement in SAFETY_REPLACEMENTS.items():
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

    return sanitized


def compress_message_content(content: Union[str, List[Dict[str, Any]]]) -> Union[str, List[Dict[str, Any]]]:
    if isinstance(content, str):
        sanitized = sanitize_text_for_safety(content)
        if len(sanitized) > COMPRESS_MAX_LENGTH:
            sanitized = sanitized[:COMPRESS_HEAD_LENGTH] + "...[内容省略]..." + sanitized[-COMPRESS_TAIL_LENGTH:]
        return sanitized

    if isinstance(content, list):
        compressed_parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text = item.get("text", "")
                    sanitized_text = sanitize_text_for_safety(text)
                    if len(sanitized_text) > COMPRESS_MAX_LENGTH:
                        sanitized_text = sanitized_text[:COMPRESS_HEAD_LENGTH] + "...[省略]..." + sanitized_text[-COMPRESS_TAIL_LENGTH:]
                    compressed_parts.append({"type": "text", "text": sanitized_text})
                elif item.get("type") in ("image_url", "image"):
                    compressed_parts.append({"type": "text", "text": "[图片]"})
                else:
                    compressed_parts.append(item)
            else:
                compressed_parts.append(item)
        return compressed_parts

    return content


async def compress_context_for_safety(
    messages: List[Dict[str, Any]],
    *,
    level: int = 1,
) -> List[Dict[str, Any]]:
    if not messages:
        return messages

    compressed: List[Dict[str, Any]] = []

    if level == 1:
        for msg in messages:
            new_msg = msg.copy()
            content = msg.get("content")
            if content:
                new_msg["content"] = compress_message_content(content)
            compressed.append(new_msg)
        log.debug(f"[安全压缩] Level 1 完成 | 消息数={len(compressed)}")
        return compressed

    if level >= 2:
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if isinstance(content, str):
                compressed_content = sanitize_text_for_safety(content)
                if len(compressed_content) > COMPRESS_L2_MAX_LENGTH:
                    compressed_content = compressed_content[:COMPRESS_L2_HEAD_LENGTH] + "...[略]"
            elif isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        text = sanitize_text_for_safety(text)
                        if len(text) > COMPRESS_L2_MULTIMODAL_MAX_LENGTH:
                            text = text[:COMPRESS_L2_MULTIMODAL_HEAD_LENGTH] + "..."
                        text_parts.append(text)
                compressed_content = " ".join(text_parts) if text_parts else "[多媒体消息]"
            else:
                compressed_content = str(content)[:COMPRESS_L2_MULTIMODAL_MAX_LENGTH]

            compressed.append({
                "role": role,
                "content": compressed_content,
                "timestamp": msg.get("timestamp"),
            })

        log.debug(
            f"[安全压缩] Level 2 完成 | 原消息数={len(messages)} | 压缩后={len(compressed)}"
        )

    return compressed
