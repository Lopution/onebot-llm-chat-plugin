"""Handlers - 主动发言 transcript 构建。"""

from __future__ import annotations

from typing import Any, Dict, List

from .utils.transcript_builder import (
    build_participants_line,
    build_transcript_lines,
    render_transcript_content as _render_transcript_content,
)


def render_transcript_content(content: Any) -> str:
    # Keep a stable, shared rendering rule with the group transcript builder.
    return _render_transcript_content(content)


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

    lines = build_transcript_lines(
        history,
        bot_name=bot_name,
        max_lines=max_lines,
        line_max_chars=200,
    )
    participants_line = build_participants_line(lines, bot_name=bot_name)
    if participants_line:
        lines = [participants_line, *lines]

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
