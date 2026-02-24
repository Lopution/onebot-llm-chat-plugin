"""LLM-powered context summarizer."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import httpx

from ..infra.logging import logger as log
from ..llm.providers import build_provider_request, parse_provider_response
from .context_schema import normalize_content
from .media_semantics import placeholder_from_content_part


class ContextSummarizer:
    """将较长历史对话压缩为短摘要。"""

    SUMMARY_SYSTEM_PROMPT = (
        "你是一个对话摘要助手。请将以下对话历史浓缩为简洁摘要，"
        "保留关键事实、用户偏好、重要决定和未完成话题。"
        "使用第三人称，不要输出多余解释。"
    )

    def _render_messages(self, messages: List[dict[str, Any]]) -> str:
        lines: list[str] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "unknown").strip() or "unknown"
            content = normalize_content(msg.get("content", ""))
            if isinstance(content, str):
                text = content.strip()
            else:
                parts: list[str] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    item_type = str(item.get("type") or "").lower()
                    if item_type == "text":
                        value = str(item.get("text") or "").strip()
                        if value:
                            parts.append(value)
                    elif item_type == "image_url":
                        parts.append(placeholder_from_content_part(item))
                text = " ".join(parts).strip()
            if text:
                lines.append(f"{role}: {text}")
        return "\n".join(lines).strip()

    async def summarize(
        self,
        messages: List[dict[str, Any]],
        *,
        api_key: str,
        base_url: str,
        model: str,
        provider: str = "openai_compat",
        extra_headers: Optional[Dict[str, str]] = None,
        max_chars: int = 500,
        existing_summary: str = "",
    ) -> str:
        """调用 LLM 生成摘要。"""
        rendered = self._render_messages(messages)
        if not rendered:
            return ""

        user_payload = rendered
        if existing_summary.strip():
            user_payload = (
                f"[已有摘要]\n{existing_summary.strip()}\n\n"
                f"[增量对话]\n{rendered}"
            )

        request_body: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": self.SUMMARY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "请输出新的完整摘要，控制在 300 字以内：\n"
                        f"{user_payload}"
                    ),
                },
            ],
            "temperature": 0.2,
            "max_tokens": 512,
            "stream": False,
        }

        request_id = uuid.uuid4().hex[:8]
        client: Optional[httpx.AsyncClient] = None
        try:
            client = httpx.AsyncClient(timeout=20.0)
            prepared = build_provider_request(
                provider=provider,
                base_url=base_url,
                model=model,
                api_key=api_key,
                request_body=request_body,
                extra_headers=extra_headers,
                default_temperature=0.2,
            )
            response = await client.post(
                prepared.url,
                headers=prepared.headers,
                params=prepared.params,
                json=prepared.json_body,
            )
            response.raise_for_status()
            payload = response.json()
            assistant_message, _, _, _ = parse_provider_response(provider=provider, data=payload)
            parsed_content = normalize_content(assistant_message.get("content", ""))
            if isinstance(parsed_content, str):
                summary = parsed_content.strip()
            else:
                text_parts: list[str] = []
                for part in parsed_content:
                    if not isinstance(part, dict):
                        continue
                    if str(part.get("type") or "").lower() == "text":
                        text = str(part.get("text") or "").strip()
                        if text:
                            text_parts.append(text)
                summary = " ".join(text_parts).strip()
            if max_chars > 0 and len(summary) > max_chars:
                summary = summary[: max(1, max_chars)].rstrip() + "…"
            return summary
        except Exception as exc:
            log.warning(
                f"[context-summary:{request_id}] 摘要生成失败 | provider={provider} | model={model} | err={exc}"
            )
            return ""
        finally:
            if client is not None and not client.is_closed:
                await client.aclose()
