"""上下文管理器：结构化归一化、按轮次截断、按 token 软上限裁剪。"""

from __future__ import annotations

from typing import Awaitable, Callable, List, Optional

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
        return self._process_normalized(normalized)

    def _process_normalized(self, normalized: List[ContextMessage]) -> List[ContextMessage]:
        """对已归一化消息执行常规截断。"""

        # legacy 模式保留旧语义：只做轻量规范化与硬上限保护
        if self.context_mode == "legacy":
            return normalized

        truncated = self._truncate_by_turns(normalized, self.max_turns)
        if self.max_tokens_soft > 0:
            truncated = self._truncate_by_soft_tokens(truncated, self.max_tokens_soft)
        return self._fix_dangling_tool_blocks(truncated)

    async def process_with_summary(
        self,
        messages: List[dict],
        *,
        summary_builder: Optional[Callable[[List[ContextMessage]], Awaitable[str]]] = None,
        summary_trigger_turns: Optional[int] = None,
        summary_max_chars: int = 500,
    ) -> List[ContextMessage]:
        """异步上下文处理：超过阈值时用摘要 + 最近轮次。

        默认行为与 `process()` 保持一致，仅在满足以下条件时启用摘要：
        - `summary_enabled=True`
        - 提供 `summary_builder`
        - 轮次超过 `summary_trigger_turns`
        """
        normalized = self.normalize(messages)
        if self.context_mode == "legacy":
            return normalized

        trigger_turns = max(1, int(summary_trigger_turns or self.max_turns))
        turns = self._split_turns(normalized)
        if (
            not self.summary_enabled
            or summary_builder is None
            or len(turns) <= trigger_turns
        ):
            return self._process_normalized(normalized)

        keep_turns = max(1, min(self.max_turns, trigger_turns, len(turns)))
        old_turns = turns[:-keep_turns]
        recent_turns = turns[-keep_turns:]

        old_messages: List[ContextMessage] = []
        for turn in old_turns:
            old_messages.extend(turn)

        recent_messages: List[ContextMessage] = []
        for turn in recent_turns:
            recent_messages.extend(turn)

        summary_text = ""
        try:
            summary_text = str(await summary_builder(old_messages) or "").strip()
        except Exception:
            summary_text = ""

        if not summary_text:
            return self._process_normalized(normalized)

        if self.max_tokens_soft > 0:
            recent_messages = self._truncate_by_soft_tokens(recent_messages, self.max_tokens_soft)

        result: List[ContextMessage] = []
        if summary_text:
            max_chars = max(50, int(summary_max_chars))
            if len(summary_text) > max_chars:
                summary_text = summary_text[:max_chars].rstrip() + "…"
            result.append({"role": "system", "content": f"[历史摘要] {summary_text}"})
        result.extend(recent_messages)
        return self._fix_dangling_tool_blocks(result)

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
                if not seen_assistant_tool_call:
                    continue
                fixed.append(msg)
                continue

            fixed.append(msg)

        # 移除开头非 user 的孤立工具块
        while fixed and fixed[0].get("role") == "tool":
            fixed.pop(0)
        return fixed
