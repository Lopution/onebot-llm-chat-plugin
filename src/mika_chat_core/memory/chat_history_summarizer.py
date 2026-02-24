"""群聊话题化摘要服务。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from ..infra.logging import logger as log
from ..llm.providers import build_provider_request, parse_provider_response
from ..utils.context_schema import normalize_content
from ..utils.media_semantics import placeholder_from_content_part
from ..utils.prompt_loader import load_prompt_yaml
from .topic_store import get_topic_store


@dataclass
class TopicCandidate:
    """话题识别候选。"""

    topic: str
    keywords: list[str]
    message_indices: list[int]


class ChatHistorySummarizer:
    """按批次识别话题并写入结构化摘要。"""

    _ANALYSIS_PROMPT_FILE = "topic_analysis.yaml"
    _SUMMARY_PROMPT_FILE = "topic_summary.yaml"

    _ANALYSIS_SYSTEM_DEFAULT = (
        "你是聊天记录分析助手。你的任务是把一段群聊按话题拆分。"
        "请输出 JSON：{\"topics\":[{\"topic\":\"...\",\"keywords\":[...],\"message_indices\":[...]}]}。"
        "message_indices 使用从 1 开始的序号。"
    )
    _ANALYSIS_USER_TEMPLATE_DEFAULT = (
        "请分析以下聊天记录并识别主要话题。\n"
        "要求：\n"
        "1. 同一条消息只归属一个最相关话题\n"
        "2. 最多输出 3 个话题\n"
        "3. 只输出 JSON，不要额外解释\n\n"
        "{messages_text}"
    )
    _SUMMARY_SYSTEM_DEFAULT = (
        "你是话题摘要助手。请基于给定消息生成结构化摘要。"
        "输出 JSON：{\"summary\":\"...\",\"key_points\":[\"...\"],\"keywords\":[\"...\"]}。"
    )
    _SUMMARY_USER_TEMPLATE_DEFAULT = (
        "话题：{topic}\n"
        "消息片段：\n"
        "{messages_text}\n\n"
        "请给出该话题的简洁摘要（120 字以内）与关键点（最多 4 条）。"
    )

    def _load_prompt_templates(self) -> Dict[str, str]:
        analysis_cfg = load_prompt_yaml(self._ANALYSIS_PROMPT_FILE)
        summary_cfg = load_prompt_yaml(self._SUMMARY_PROMPT_FILE)
        return {
            "analysis_system": str(
                analysis_cfg.get("topic_analysis_system_prompt")
                or self._ANALYSIS_SYSTEM_DEFAULT
            ).strip(),
            "analysis_user_template": str(
                analysis_cfg.get("topic_analysis_user_template")
                or self._ANALYSIS_USER_TEMPLATE_DEFAULT
            ).strip(),
            "summary_system": str(
                summary_cfg.get("topic_summary_system_prompt")
                or self._SUMMARY_SYSTEM_DEFAULT
            ).strip(),
            "summary_user_template": str(
                summary_cfg.get("topic_summary_user_template")
                or self._SUMMARY_USER_TEMPLATE_DEFAULT
            ).strip(),
        }

    def _extract_text(self, message: dict[str, Any]) -> str:
        content = normalize_content(message.get("content", ""))
        if isinstance(content, str):
            return content.strip()
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").lower()
            if item_type == "text":
                value = str(item.get("text") or "").strip()
                if value:
                    text_parts.append(value)
            elif item_type == "image_url":
                text_parts.append(placeholder_from_content_part(item))
        return " ".join(text_parts).strip()

    def _render_messages(self, messages: List[dict[str, Any]]) -> str:
        lines: list[str] = []
        for index, message in enumerate(messages, start=1):
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "unknown").strip() or "unknown"
            text = self._extract_text(message)
            if not text:
                continue
            lines.append(f"{index}. {role}: {text}")
        return "\n".join(lines).strip()

    @staticmethod
    def _extract_json_payload(raw_text: str) -> Any:
        text = str(raw_text or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            pass

        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if not match:
            return None
        snippet = match.group(1)
        try:
            return json.loads(snippet)
        except Exception:
            return None

    async def _call_llm(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        llm_cfg: Dict[str, Any],
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> str:
        api_keys = list(llm_cfg.get("api_keys") or [])
        if not api_keys:
            return ""

        request_body: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": False,
        }

        prepared = build_provider_request(
            provider=str(llm_cfg.get("provider") or "openai_compat"),
            base_url=str(llm_cfg.get("base_url") or ""),
            model=model,
            api_key=str(api_keys[0] or ""),
            request_body=request_body,
            extra_headers=dict(llm_cfg.get("extra_headers") or {}),
            default_temperature=float(temperature),
        )

        client: Optional[httpx.AsyncClient] = None
        try:
            client = httpx.AsyncClient(timeout=20.0)
            response = await client.post(
                prepared.url,
                headers=prepared.headers,
                params=prepared.params,
                json=prepared.json_body,
            )
            response.raise_for_status()
            payload = response.json()
            assistant_message, _, _, _ = parse_provider_response(
                provider=str(llm_cfg.get("provider") or "openai_compat"),
                data=payload,
            )
            content = normalize_content(assistant_message.get("content", ""))
            if isinstance(content, str):
                return content.strip()
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if str(part.get("type") or "").lower() != "text":
                    continue
                text = str(part.get("text") or "").strip()
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()
        except Exception as exc:
            log.warning(f"[topic-summary] LLM 调用失败 | model={model} | error={exc}")
            return ""
        finally:
            if client is not None and not client.is_closed:
                await client.aclose()

    @staticmethod
    def _normalize_topics(payload: Any, message_count: int) -> list[TopicCandidate]:
        if not isinstance(payload, dict):
            return []
        raw_topics = payload.get("topics")
        if not isinstance(raw_topics, list):
            return []
        topics: list[TopicCandidate] = []
        for item in raw_topics[:3]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("topic") or "").strip()
            if not name:
                continue
            raw_keywords = item.get("keywords", [])
            keywords = []
            if isinstance(raw_keywords, list):
                keywords = [str(value).strip() for value in raw_keywords if str(value).strip()]
            raw_indices = item.get("message_indices", [])
            indices: list[int] = []
            if isinstance(raw_indices, list):
                for value in raw_indices:
                    try:
                        index = int(value)
                    except Exception:
                        continue
                    if 1 <= index <= message_count:
                        indices.append(index)
            dedup_indices = sorted(set(indices))
            topics.append(TopicCandidate(topic=name, keywords=keywords, message_indices=dedup_indices))
        return topics

    @staticmethod
    def _slice_messages(messages: List[dict[str, Any]], indices: List[int]) -> List[dict[str, Any]]:
        if not indices:
            return list(messages)
        mapped: list[dict[str, Any]] = []
        for index in indices:
            if 1 <= index <= len(messages):
                mapped.append(messages[index - 1])
        return mapped or list(messages)

    @staticmethod
    def _extract_participants(messages: List[dict[str, Any]]) -> list[str]:
        participants: list[str] = []
        for message in messages:
            text = str(message.get("content") or "")
            match = re.match(r"^\[([^\]]+)\]:", text)
            if not match:
                continue
            tag = match.group(1).strip()
            if tag and tag not in participants:
                participants.append(tag)
        return participants

    @staticmethod
    def _resolve_timestamps(messages: List[dict[str, Any]]) -> tuple[float, float]:
        timestamps: list[float] = []
        for message in messages:
            try:
                value = float(message.get("timestamp") or 0.0)
            except Exception:
                value = 0.0
            if value > 0:
                timestamps.append(value)
        if not timestamps:
            return 0.0, 0.0
        return min(timestamps), max(timestamps)

    @staticmethod
    def _parse_topic_summary(payload: Any, fallback_text: str) -> tuple[str, list[str], list[str]]:
        if isinstance(payload, dict):
            summary = str(payload.get("summary") or "").strip()
            raw_points = payload.get("key_points", [])
            raw_keywords = payload.get("keywords", [])
            key_points = (
                [str(item).strip() for item in raw_points if str(item).strip()]
                if isinstance(raw_points, list)
                else []
            )
            keywords = (
                [str(item).strip() for item in raw_keywords if str(item).strip()]
                if isinstance(raw_keywords, list)
                else []
            )
            if summary:
                return summary, key_points[:4], keywords[:6]
        return str(fallback_text or "").strip(), [], []

    async def maybe_summarize(
        self,
        *,
        session_key: str,
        messages: List[dict[str, Any]],
        llm_cfg: Dict[str, Any],
        model: str,
        batch_size: int = 25,
        request_id: str = "",
    ) -> int:
        """按会话消息增量生成话题摘要。"""
        if not session_key or not messages:
            return 0
        if not model:
            return 0

        store = get_topic_store()
        await store.init_table()

        safe_batch = max(5, int(batch_size or 25))
        total_count = len(messages)
        processed_count = await store.get_processed_message_count(session_key)
        if processed_count > total_count:
            processed_count = 0
            await store.set_processed_message_count(session_key, 0)

        pending = total_count - processed_count
        if pending < safe_batch:
            return 0

        batch_messages = list(messages[processed_count : processed_count + safe_batch])
        next_processed_count = processed_count + len(batch_messages)
        rendered_batch = self._render_messages(batch_messages)
        if not rendered_batch:
            await store.set_processed_message_count(session_key, next_processed_count)
            return 0

        prompts = self._load_prompt_templates()
        analysis_user = prompts["analysis_user_template"].replace("{messages_text}", rendered_batch)
        analysis_raw = await self._call_llm(
            system_prompt=prompts["analysis_system"],
            user_prompt=analysis_user,
            llm_cfg=llm_cfg,
            model=model,
            temperature=0.0,
            max_tokens=768,
        )

        candidates = self._normalize_topics(self._extract_json_payload(analysis_raw), len(batch_messages))
        if not candidates:
            candidates = [
                TopicCandidate(
                    topic="对话片段",
                    keywords=[],
                    message_indices=list(range(1, len(batch_messages) + 1)),
                )
            ]

        stored = 0
        for candidate in candidates:
            topic_messages = self._slice_messages(batch_messages, candidate.message_indices)
            rendered_topic_messages = self._render_messages(topic_messages)
            if not rendered_topic_messages:
                continue

            summary_user = (
                prompts["summary_user_template"]
                .replace("{topic}", candidate.topic)
                .replace("{messages_text}", rendered_topic_messages)
            )
            summary_raw = await self._call_llm(
                system_prompt=prompts["summary_system"],
                user_prompt=summary_user,
                llm_cfg=llm_cfg,
                model=model,
                temperature=0.2,
                max_tokens=512,
            )
            summary_text, key_points, summary_keywords = self._parse_topic_summary(
                self._extract_json_payload(summary_raw),
                summary_raw,
            )
            if not summary_text:
                continue
            keywords = candidate.keywords or summary_keywords
            participants = self._extract_participants(topic_messages)
            timestamp_start, timestamp_end = self._resolve_timestamps(topic_messages)
            topic_id = await store.upsert_topic_summary(
                session_key=session_key,
                topic=candidate.topic,
                keywords=keywords,
                summary=summary_text,
                key_points=key_points,
                participants=participants,
                timestamp_start=timestamp_start,
                timestamp_end=timestamp_end,
                source_message_count=len(topic_messages),
            )
            if topic_id:
                stored += 1

        if stored > 0:
            log.info(
                f"[topic-summary][req:{request_id or '-'}] 会话摘要更新 | "
                f"session={session_key} | topics={stored} | processed={next_processed_count}/{total_count}"
            )
            await store.set_processed_message_count(session_key, next_processed_count)
        return stored


_chat_history_summarizer: ChatHistorySummarizer | None = None


def get_chat_history_summarizer() -> ChatHistorySummarizer:
    global _chat_history_summarizer
    if _chat_history_summarizer is None:
        _chat_history_summarizer = ChatHistorySummarizer()
    return _chat_history_summarizer
