"""上下文管理器：结构化归一化、按轮次截断、按 token 软上限裁剪。"""

from __future__ import annotations

from typing import List

from .context_schema import (
    ContextMessage,
    estimate_message_tokens,
    normalize_context_messages,
)


class ContextManager:
    """聊天上下文管理器。"""

    def __init__(
        self,
        *,
        context_mode: str = "structured",
        max_turns: int = 30,
        max_tokens_soft: int = 12000,
        summary_enabled: bool = False,
        hard_max_messages: int = 160,
    ) -> None:
        self.context_mode = context_mode
        self.max_turns = max(1, int(max_turns))
        self.max_tokens_soft = max(0, int(max_tokens_soft))
        self.summary_enabled = bool(summary_enabled)
        self.hard_max_messages = max(10, int(hard_max_messages))

    def normalize(self, messages: List[dict]) -> List[ContextMessage]:
        normalized = normalize_context_messages(messages)
        if len(normalized) > self.hard_max_messages:
            normalized = normalized[-self.hard_max_messages :]
        return self._fix_dangling_tool_blocks(normalized)

    def process(self, messages: List[dict]) -> List[ContextMessage]:
        normalized = self.normalize(messages)

        # legacy 模式保留旧语义：只做轻量规范化与硬上限保护
        if self.context_mode == "legacy":
            return normalized

        truncated = self._truncate_by_turns(normalized, self.max_turns)
        if self.max_tokens_soft > 0:
            truncated = self._truncate_by_soft_tokens(truncated, self.max_tokens_soft)
        return self._fix_dangling_tool_blocks(truncated)

    def _split_turns(self, messages: List[ContextMessage]) -> List[List[ContextMessage]]:
        turns: List[List[ContextMessage]] = []
        current: List[ContextMessage] = []

        for msg in messages:
            role = msg.get("role")
            if role == "user":
                if current:
                    turns.append(current)
                current = [msg]
            else:
                current.append(msg)

        if current:
            turns.append(current)
        return turns

    def _truncate_by_turns(self, messages: List[ContextMessage], keep_turns: int) -> List[ContextMessage]:
        if keep_turns <= 0:
            return []
        turns = self._split_turns(messages)
        if len(turns) <= keep_turns:
            return messages
        kept_turns = turns[-keep_turns:]
        flattened: List[ContextMessage] = []
        for turn in kept_turns:
            flattened.extend(turn)
        return flattened

    def _truncate_by_soft_tokens(
        self, messages: List[ContextMessage], soft_limit: int
    ) -> List[ContextMessage]:
        turns = self._split_turns(messages)
        if not turns:
            return messages

        def _count_tokens(turn_groups: List[List[ContextMessage]]) -> int:
            return sum(estimate_message_tokens(msg) for turn in turn_groups for msg in turn)

        while len(turns) > 1 and _count_tokens(turns) > soft_limit:
            turns.pop(0)

        flattened: List[ContextMessage] = []
        for turn in turns:
            flattened.extend(turn)
        return flattened

    def _fix_dangling_tool_blocks(self, messages: List[ContextMessage]) -> List[ContextMessage]:
        fixed: List[ContextMessage] = []
        seen_user = False
        seen_assistant_tool_call = False

        for msg in messages:
            role = msg.get("role")
            if role == "user":
                seen_user = True
                seen_assistant_tool_call = False
                fixed.append(msg)
                continue

            if role == "assistant":
                tool_calls = msg.get("tool_calls")
                if isinstance(tool_calls, list) and tool_calls:
                    if not seen_user:
                        continue
                    seen_assistant_tool_call = True
                fixed.append(msg)
                continue

            if role == "tool":
                # tool 消息前必须已经有一条 user 与 assistant(tool_calls) 语义上下文
                if not seen_user:
                    continue
                if not seen_assistant_tool_call and not fixed:
                    continue
                fixed.append(msg)
                continue

            fixed.append(msg)

        # 移除开头非 user 的孤立工具块
        while fixed and fixed[0].get("role") == "tool":
            fixed.pop(0)
        return fixed
