"""Lightweight LLM-based relevance filter for group replies."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import httpx

from ..infra.logging import logger as log
from ..llm.providers import (
    build_provider_request,
    detect_provider_name,
    get_provider_capabilities,
    parse_provider_response,
)
from ..utils.prompt_loader import load_prompt_yaml
from .filter_types import FilterResult

_DEFAULT_TEMPLATE = """
你是群聊消息相关性过滤器。判断机器人是否应该回复当前消息。

输出 JSON：
{
  "should_reply": true/false,
  "reasoning": "简短原因",
  "confidence": 0.0-1.0
}

判断原则：
1) 纯表情、无意义测试、明显噪声 -> should_reply=false
2) 明确提问、点名、需要信息/情绪回应 -> should_reply=true
3) 不确定时偏向 true（避免误杀正常消息）
""".strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _render_context_preview(context_messages: List[Dict[str, Any]], max_lines: int = 12) -> str:
    # Use the same transcript rules as the main group working set so we don't
    # lose speaker identity in multi-user chatrooms.
    try:
        from ..utils.transcript_builder import build_transcript_lines

        rendered = build_transcript_lines(
            context_messages or [],
            bot_name="Mika",
            max_lines=max(1, int(max_lines or 12)),
            line_max_chars=120,
        )
        return "\n".join(rendered).strip()
    except Exception:
        # Fallback to a minimal preview on any unexpected errors.
        lines: List[str] = []
        for msg in (context_messages or [])[-max_lines:]:
            role = str(msg.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = msg.get("content", "")
            text = str(content if isinstance(content, str) else "").replace("\n", " ").strip()
            if not text:
                continue
            if len(text) > 120:
                text = text[:120] + "..."
            speaker = "Mika" if role == "assistant" else "User"
            lines.append(f"{speaker}: {text}")
        return "\n".join(lines).strip()


class RelevanceFilter:
    """LLM relevance filter (yes/no + confidence)."""

    def __init__(self) -> None:
        self._template_cache: Optional[str] = None
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

    async def _get_client(self, *, timeout_seconds: float) -> httpx.AsyncClient:
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

    def _load_template(self) -> str:
        if self._template_cache is not None:
            return self._template_cache
        try:
            cfg = load_prompt_yaml("relevance_filter.yaml")
            if isinstance(cfg, dict):
                node = cfg.get("relevance_filter", cfg)
                if isinstance(node, dict):
                    template = str(node.get("template") or "").strip()
                    if template:
                        self._template_cache = template
                        return template
        except Exception:
            pass
        self._template_cache = _DEFAULT_TEMPLATE
        return self._template_cache

    def _parse_result(self, raw: str) -> FilterResult:
        content = str(raw or "").strip()
        if not content:
            return FilterResult(should_reply=True, reasoning="empty_result", confidence=0.0)
        try:
            payload = json.loads(content)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", content)
            if not match:
                return FilterResult(should_reply=True, reasoning="invalid_json", confidence=0.0)
            try:
                payload = json.loads(match.group(0))
            except Exception:
                return FilterResult(should_reply=True, reasoning="invalid_json", confidence=0.0)

        should_reply = bool(payload.get("should_reply", True))
        reasoning = str(payload.get("reasoning") or "").strip() or "no_reason"
        confidence = max(0.0, min(1.0, _safe_float(payload.get("confidence"), 0.0)))
        return FilterResult(should_reply=should_reply, reasoning=reasoning, confidence=confidence)

    async def evaluate(
        self,
        *,
        message: str,
        context_messages: List[Dict[str, Any]],
        llm_cfg: Dict[str, Any],
        model: str,
        temperature: float = 0.0,
        timeout_seconds: float = 12.0,
    ) -> FilterResult:
        text = str(message or "").strip()
        if not text:
            return FilterResult(should_reply=False, reasoning="empty_message", confidence=1.0)

        provider = detect_provider_name(
            configured_provider=str(llm_cfg.get("provider") or "openai_compat"),
            base_url=str(llm_cfg.get("base_url") or ""),
        )
        api_keys = list(llm_cfg.get("api_keys") or [])
        if not api_keys:
            return FilterResult(should_reply=True, reasoning="missing_api_key", confidence=0.0)

        template = self._load_template()
        context_preview = _render_context_preview(context_messages)
        user_prompt = (
            f"[最近上下文]\n{context_preview or '(无)'}\n\n"
            f"[当前消息]\n{text}\n\n"
            "请给出 JSON 结果。"
        )
        request_body: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": template},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": 256,
            "stream": False,
        }
        capabilities = get_provider_capabilities(
            configured_provider=provider,
            base_url=str(llm_cfg.get("base_url") or ""),
            model=model,
        )
        if capabilities.supports_json_object_response:
            request_body["response_format"] = {"type": "json_object"}

        prepared = build_provider_request(
            provider=provider,
            base_url=str(llm_cfg.get("base_url") or ""),
            model=model,
            api_key=str(api_keys[0] or ""),
            request_body=request_body,
            extra_headers=dict(llm_cfg.get("extra_headers") or {}),
            default_temperature=float(temperature),
        )
        client = await self._get_client(timeout_seconds=timeout_seconds)
        try:
            response = await client.post(
                prepared.url,
                headers=prepared.headers,
                params=prepared.params,
                json=prepared.json_body,
            )
            response.raise_for_status()
            payload = response.json()
            assistant_message, _, _, _ = parse_provider_response(provider=provider, data=payload)
            raw = str(assistant_message.get("content") or "").strip()
            return self._parse_result(raw)
        except Exception as exc:
            log.warning(f"[RelevanceFilter] evaluate failed: {exc}")
            return FilterResult(should_reply=True, reasoning=f"filter_error:{type(exc).__name__}", confidence=0.0)


_singleton: RelevanceFilter | None = None


def get_relevance_filter() -> RelevanceFilter:
    global _singleton
    if _singleton is None:
        _singleton = RelevanceFilter()
    return _singleton


async def close_relevance_filter() -> None:
    global _singleton
    if _singleton is None:
        return
    await _singleton.close()
    _singleton = None


__all__ = ["RelevanceFilter", "get_relevance_filter", "close_relevance_filter"]
