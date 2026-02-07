"""Gemini API - 主动发言判决与 JSON 提取工具。"""

from __future__ import annotations

from typing import Optional


def extract_json_object(text: str) -> Optional[str]:
    """
    从文本中健壮地提取 JSON 对象（支持嵌套花括号）。

    Args:
        text: 可能包含 JSON 的文本

    Returns:
        提取出的 JSON 字符串，如果未找到则返回 None
    """
    if not text:
        return None

    text = text.strip()
    start_index = text.find("{")
    if start_index == -1:
        return None

    balance = 0
    for i in range(start_index, len(text)):
        char = text[i]
        if char == "{":
            balance += 1
        elif char == "}":
            balance -= 1

        if balance == 0:
            return text[start_index : i + 1]

    return None
