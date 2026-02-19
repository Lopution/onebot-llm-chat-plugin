"""Handlers - 主动发言 transcript 构建。"""

from __future__ import annotations

import re
from typing import Any, Dict, List


def render_transcript_content(content: Any) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "text":
                parts.append(str(item.get("text") or ""))
            elif item_type == "image_url":
                parts.append("[图片]")
        text = " ".join(part for part in parts if part)
    else:
        text = str(content or "")
    return " ".join(text.split())


def build_proactive_chatroom_injection(
    history: List[Dict[str, Any]],
    *,
    bot_name: str,
    max_lines: int,
    trigger_message: str = "",
    trigger_sender: str = "",
) -> str:
    if max_lines <= 0:
        return ""

    lines: List[str] = []
    for msg in (history or [])[-max_lines:]:
        role = msg.get("role")
        content = render_transcript_content(msg.get("content"))
        if not content:
            continue

        content = content.replace("\n", " ").strip()
        if len(content) > 200:
            content = content[:200] + "…"

        if role == "assistant":
            lines.append(f"{bot_name}: {content}")
            continue

        matched = re.match(r"^\[(.*?)\]:\s*(.*)$", content)
        if matched:
            speaker = (matched.group(1) or "").strip()
            said = (matched.group(2) or "").strip()
            if speaker and said:
                lines.append(f"{speaker}: {said}")
                continue

        lines.append(content)

    transcript = "\n".join(lines).strip()
    if not transcript:
        transcript = "(无最近记录)"

    trigger_marker = ""
    if trigger_message:
        trigger_preview = trigger_message[:150] + "..." if len(trigger_message) > 150 else trigger_message
        sender_label = trigger_sender if trigger_sender else "某位群友"
        trigger_marker = f"\n---\nNow, a new message is coming from {sender_label}: `{trigger_preview}`"

    return (
        "[System Instruction - Chatroom Transcript]\n"
        "下面是最近的群聊记录，用于理解聊天氛围与上下文。\n"
        f"{transcript}"
        f"{trigger_marker}\n"
        "[End Transcript]\n"
        "请根据群聊上下文，自然地回应上面标记的新消息。可以适当结合正在讨论的话题。\n"
        "回复语言：优先使用触发消息的语言；若不确定，使用上述记录最后几条消息的主要语言。"
    )
