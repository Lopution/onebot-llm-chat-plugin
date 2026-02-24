"""ReAct 风格记忆检索 Agent。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from ..infra.logging import logger as log
from ..llm.providers import build_provider_request, parse_provider_response
from ..mika_api_layers.core.proactive import extract_json_object
from ..utils.context_schema import normalize_content
from ..utils.knowledge_store import get_knowledge_store
from ..utils.memory_store import get_memory_store
from ..utils.prompt_loader import load_prompt_yaml
from ..utils.semantic_matcher import semantic_matcher
from ..utils.user_profile import get_user_profile_store
from .topic_store import get_topic_store


@dataclass
class RetrievalDecision:
    """单轮 ReAct 决策。"""

    action: str
    args: Dict[str, Any]
    reason: str


@dataclass
class RetrievalObservation:
    """单轮工具观察结果。"""

    action: str
    observation: str


class MemoryRetrievalAgent:
    """在回复前进行多源记忆检索。"""

    _PROMPT_FILE = "memory_retrieval.yaml"
    _DEFAULT_SYSTEM_PROMPT = (
        "你是记忆检索规划器。请在 query_chat_history/query_user_profile/query_memory/query_knowledge/"
        "found_answer 中选择下一步动作，并输出 JSON。"
    )
    _DEFAULT_USER_TEMPLATE = (
        "[当前问题]\n{question}\n\n[会话]\nsession_key={session_key}\nuser_id={user_id}\n"
        "group_id={group_id}\n\n[已观察结果]\n{observations}\n\n请给出下一步动作 JSON。"
    )

    def __init__(self) -> None:
        self._http_client: Optional[httpx.AsyncClient] = None
        self._client_timeout_seconds: float = 0.0
        self._client_loop_id: Optional[int] = None
        self._client_lock: Optional[asyncio.Lock] = None
        self._client_lock_loop_id: Optional[int] = None

    @staticmethod
    def _get_loop_id() -> int:
        return id(asyncio.get_running_loop())

    def _get_client_lock(self) -> asyncio.Lock:
        loop_id = self._get_loop_id()
        if self._client_lock is None or self._client_lock_loop_id != loop_id:
            self._client_lock = asyncio.Lock()
            self._client_lock_loop_id = loop_id
        return self._client_lock

    async def _get_http_client(self, *, timeout_seconds: float) -> httpx.AsyncClient:
        expected_timeout = max(1.0, float(timeout_seconds))
        loop_id = self._get_loop_id()

        async with self._get_client_lock():
            if (
                self._http_client is not None
                and not self._http_client.is_closed
                and self._client_loop_id is not None
                and self._client_loop_id != loop_id
            ):
                try:
                    await self._http_client.aclose()
                finally:
                    self._http_client = None
                    self._client_timeout_seconds = 0.0
                    self._client_loop_id = None

            if (
                self._http_client is None
                or self._http_client.is_closed
                or abs(self._client_timeout_seconds - expected_timeout) > 1e-6
            ):
                if self._http_client is not None and not self._http_client.is_closed:
                    try:
                        await self._http_client.aclose()
                    except Exception:
                        pass
                self._http_client = httpx.AsyncClient(timeout=expected_timeout)
                self._client_timeout_seconds = expected_timeout
                self._client_loop_id = loop_id

            return self._http_client

    async def close(self) -> None:
        async with self._get_client_lock():
            if self._http_client is not None and not self._http_client.is_closed:
                await self._http_client.aclose()
            self._http_client = None
            self._client_timeout_seconds = 0.0
            self._client_loop_id = None

    def _load_prompt_templates(self) -> tuple[str, str]:
        cfg = load_prompt_yaml(self._PROMPT_FILE)
        system_prompt = str(
            cfg.get("memory_retrieval_system_prompt") or self._DEFAULT_SYSTEM_PROMPT
        ).strip()
        user_template = str(
            cfg.get("memory_retrieval_user_template") or self._DEFAULT_USER_TEMPLATE
        ).strip()
        return system_prompt, user_template

    async def _call_llm(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        llm_cfg: Dict[str, Any],
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        provider_name = str(llm_cfg.get("provider") or "openai_compat")
        base_url = str(llm_cfg.get("base_url") or "")
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
            provider=provider_name,
            base_url=base_url,
            model=model,
            api_key=str(api_keys[0] or ""),
            request_body=request_body,
            extra_headers=dict(llm_cfg.get("extra_headers") or {}),
            default_temperature=float(temperature),
        )

        try:
            client = await self._get_http_client(timeout_seconds=15.0)
            response = await client.post(
                prepared.url,
                headers=prepared.headers,
                params=prepared.params,
                json=prepared.json_body,
            )
            response.raise_for_status()
            payload = response.json()
            assistant_message, _, _, _ = parse_provider_response(
                provider=provider_name,
                data=payload,
            )
            parsed = normalize_content(assistant_message.get("content", ""))
            if isinstance(parsed, str):
                return parsed.strip()
            text_parts: list[str] = []
            for part in parsed:
                if not isinstance(part, dict):
                    continue
                if str(part.get("type") or "").lower() != "text":
                    continue
                value = str(part.get("text") or "").strip()
                if value:
                    text_parts.append(value)
            return "\n".join(text_parts).strip()
        except httpx.HTTPStatusError as exc:
            status_code = int(getattr(exc.response, "status_code", 0) or 0)
            body_preview = ""
            try:
                body_preview = str(getattr(exc.response, "text", "") or "").strip()
            except Exception:
                body_preview = ""
            body_preview = body_preview.replace("\n", " ")
            if len(body_preview) > 240:
                body_preview = body_preview[:240] + "..."
            log.warning(
                f"[memory-retrieval] 规划调用失败 | model={model} | provider={provider_name} | "
                f"base_url={base_url} | status={status_code} | body={body_preview!r}"
            )
            return ""
        except Exception as exc:
            log.warning(
                f"[memory-retrieval] 规划调用失败 | model={model} | provider={provider_name} | "
                f"base_url={base_url} | err_type={type(exc).__name__} | err={exc!r}",
                exc_info=True,
            )
            return ""

    @staticmethod
    def _parse_decision(raw_text: str) -> Optional[RetrievalDecision]:
        text = str(raw_text or "").strip()
        if not text:
            return None

        payload: Any = None
        extracted = extract_json_object(text)
        if extracted:
            try:
                payload = json.loads(extracted)
            except Exception:
                payload = None

        if payload is None:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    payload = json.loads(match.group(0))
                except Exception:
                    payload = None
        if not isinstance(payload, dict):
            return None

        action = str(payload.get("action") or "").strip().lower()
        if not action:
            return None
        args = payload.get("args")
        if not isinstance(args, dict):
            args = {}
        reason = str(payload.get("reason") or "").strip()
        return RetrievalDecision(action=action, args=args, reason=reason)

    @staticmethod
    def _format_observations(observations: List[RetrievalObservation]) -> str:
        if not observations:
            return "(无)"
        lines: list[str] = []
        for index, item in enumerate(observations, start=1):
            lines.append(f"{index}. {item.action}: {item.observation}")
        return "\n".join(lines)

    async def _decide_next_action(
        self,
        *,
        question: str,
        session_key: str,
        user_id: str,
        group_id: Optional[str],
        observations: List[RetrievalObservation],
        llm_cfg: Dict[str, Any],
        model: str,
    ) -> Optional[RetrievalDecision]:
        system_prompt, user_template = self._load_prompt_templates()
        user_prompt = (
            user_template.replace("{question}", question)
            .replace("{session_key}", session_key)
            .replace("{user_id}", user_id)
            .replace("{group_id}", str(group_id or ""))
            .replace("{observations}", self._format_observations(observations))
        )
        raw = await self._call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            llm_cfg=llm_cfg,
            model=model,
            temperature=0.0,
            max_tokens=512,
        )
        return self._parse_decision(raw)

    async def _query_chat_history(
        self,
        *,
        session_key: str,
        args: Dict[str, Any],
    ) -> str:
        limit = max(1, min(int(args.get("top_k", 3) or 3), 10))
        topics = await get_topic_store().list_topics(session_key, limit=limit)
        if not topics:
            return "未命中话题摘要。"
        lines: list[str] = []
        for item in topics:
            keywords = ", ".join(item.keywords[:4])
            lines.append(
                f"[{item.topic}] {item.summary}"
                + (f" | 关键词: {keywords}" if keywords else "")
            )
        return " ; ".join(lines)

    async def _query_user_profile(
        self,
        *,
        user_id: str,
        args: Dict[str, Any],
    ) -> str:
        target_user_id = str(args.get("user_id") or user_id or "").strip()
        if not target_user_id:
            return "无法确定用户ID。"
        summary = await get_user_profile_store().get_profile_summary(target_user_id)
        return summary or f"用户 {target_user_id} 暂无档案摘要。"

    async def _query_memory(
        self,
        *,
        question: str,
        session_key: str,
        args: Dict[str, Any],
        min_similarity: float,
    ) -> str:
        query = str(args.get("query") or question or "").strip()
        if not query:
            return "缺少检索 query。"
        top_k = max(1, min(int(args.get("top_k", 3) or 3), 10))
        query_embedding = semantic_matcher.encode(query)
        if query_embedding is None:
            return "向量模型不可用，无法检索长期记忆。"

        store = get_memory_store()
        await store.init_table()
        rows = await store.search(
            query_embedding,
            session_key=session_key,
            top_k=top_k,
            min_similarity=float(min_similarity),
        )
        if not rows:
            return "未命中长期记忆。"

        lines: list[str] = []
        for entry, score in rows:
            lines.append(f"({score:.3f}) {entry.fact}")
            await store.update_recall(entry.id)
        return " ; ".join(lines)

    async def _query_knowledge(
        self,
        *,
        question: str,
        session_key: str,
        args: Dict[str, Any],
        min_similarity: float,
        default_corpus: str,
    ) -> str:
        query = str(args.get("query") or question or "").strip()
        if not query:
            return "缺少检索 query。"
        top_k = max(1, min(int(args.get("top_k", 3) or 3), 10))
        corpus_id = str(args.get("corpus_id") or default_corpus or "default").strip() or "default"
        query_embedding = semantic_matcher.encode(query)
        if query_embedding is None:
            return "向量模型不可用，无法检索知识库。"

        store = get_knowledge_store()
        await store.init_table()
        rows = await store.search(
            query_embedding,
            corpus_id=corpus_id,
            session_key=session_key,
            top_k=top_k,
            min_similarity=float(min_similarity),
        )
        if not rows:
            return "未命中知识库。"

        lines: list[str] = []
        for entry, score in rows:
            snippet = str(entry.content or "").replace("\n", " ").strip()
            if len(snippet) > 180:
                snippet = snippet[:180] + "..."
            title = entry.title or entry.doc_id
            lines.append(f"({score:.3f}) [{title}] {snippet}")
            await store.update_recall(entry.id)
        return " ; ".join(lines)

    async def _execute_action(
        self,
        *,
        decision: RetrievalDecision,
        question: str,
        session_key: str,
        user_id: str,
        group_id: Optional[str],
        min_similarity: float,
        default_corpus: str,
    ) -> str:
        action = decision.action
        if action == "query_chat_history":
            return await self._query_chat_history(session_key=session_key, args=decision.args)
        if action == "query_user_profile":
            return await self._query_user_profile(user_id=user_id, args=decision.args)
        if action == "query_memory":
            return await self._query_memory(
                question=question,
                session_key=session_key,
                args=decision.args,
                min_similarity=min_similarity,
            )
        if action == "query_knowledge":
            return await self._query_knowledge(
                question=question,
                session_key=session_key,
                args=decision.args,
                min_similarity=min_similarity,
                default_corpus=default_corpus,
            )
        if action == "found_answer":
            return str(decision.args.get("answer") or decision.reason or "").strip()
        return f"不支持的动作: {action}"

    @staticmethod
    def _compose_final_context(observations: List[RetrievalObservation], final_answer: str = "") -> str:
        if final_answer:
            return final_answer.strip()
        if not observations:
            return ""
        lines: list[str] = []
        for item in observations[-3:]:
            if not item.observation.strip():
                continue
            lines.append(f"- {item.action}: {item.observation}")
        if not lines:
            return ""
        return "检索结论：\n" + "\n".join(lines)

    async def retrieve(
        self,
        *,
        question: str,
        session_key: str,
        user_id: str,
        group_id: Optional[str],
        llm_cfg: Dict[str, Any],
        model: str,
        max_iterations: int = 3,
        timeout_seconds: float = 15.0,
        min_similarity: float = 0.5,
        default_corpus: str = "default",
    ) -> str:
        """执行 ReAct 检索并返回可注入 system 的摘要。"""
        question_text = str(question or "").strip()
        if not question_text or not model:
            return ""

        safe_iterations = max(1, int(max_iterations or 1))
        deadline = time.monotonic() + max(1.0, float(timeout_seconds or 1.0))
        observations: List[RetrievalObservation] = []

        for _ in range(safe_iterations):
            if time.monotonic() >= deadline:
                break
            decision = await self._decide_next_action(
                question=question_text,
                session_key=session_key,
                user_id=user_id,
                group_id=group_id,
                observations=observations,
                llm_cfg=llm_cfg,
                model=model,
            )
            if decision is None:
                break

            observation = await self._execute_action(
                decision=decision,
                question=question_text,
                session_key=session_key,
                user_id=user_id,
                group_id=group_id,
                min_similarity=min_similarity,
                default_corpus=default_corpus,
            )

            if decision.action == "found_answer":
                return self._compose_final_context(observations, final_answer=observation)

            observations.append(
                RetrievalObservation(action=decision.action, observation=str(observation or "").strip())
            )

        return self._compose_final_context(observations)


_memory_retrieval_agent: MemoryRetrievalAgent | None = None


def get_memory_retrieval_agent() -> MemoryRetrievalAgent:
    global _memory_retrieval_agent
    if _memory_retrieval_agent is None:
        _memory_retrieval_agent = MemoryRetrievalAgent()
    return _memory_retrieval_agent


async def close_memory_retrieval_agent() -> None:
    global _memory_retrieval_agent
    if _memory_retrieval_agent is None:
        return
    await _memory_retrieval_agent.close()
    _memory_retrieval_agent = None
