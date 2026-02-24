"""从对话中提取长期记忆事实（LLM 驱动）。"""

from __future__ import annotations

import re
import inspect
from typing import Any, Dict, List, Optional

import httpx

from ..infra.logging import logger as log
from ..llm.providers import build_provider_request, parse_provider_response
from .context_schema import normalize_content


EXTRACT_SYSTEM_PROMPT = (
    "你是一个信息提取助手。从对话中提取值得长期记住的关键事实。\n"
    "只提取具体、可复用的信息（偏好、身份、经历、计划、关系）。\n"
    "不要提取临时信息（天气、当前时间、新闻）或流程信息。\n"
    "每条事实一行，格式：user_id: 事实内容\n"
    "如果 user_id 无法确定，使用 unknown。\n"
    "如果没有可提取内容，仅输出 NONE。"
)


class MemoryExtractor:
    """从对话中提取长期记忆事实。"""

    def _render_messages(self, messages: List[dict[str, Any]]) -> str:
        lines: list[str] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip()
            content = normalize_content(msg.get("content", ""))
            if isinstance(content, str):
                text = content.strip()
            else:
                parts: list[str] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("type") or "").lower() == "text":
                        value = str(item.get("text") or "").strip()
                        if value:
                            parts.append(value)
                text = " ".join(parts)
            if role in {"user", "assistant"} and text:
                lines.append(f"{role}: {text}")
        return "\n".join(lines).strip()

    def _parse_facts(self, raw: str, max_facts: int = 5) -> list[tuple[str, str]]:
        if not raw or "NONE" in raw.strip().upper():
            return []

        facts: list[tuple[str, str]] = []
        for line in raw.strip().splitlines():
            text = line.strip()
            if not text:
                continue
            match = re.match(r"^(\S+?):\s*(.+)$", text)
            if not match:
                continue
            user_id = match.group(1).strip()
            fact = match.group(2).strip()
            if len(fact) < 3:
                continue
            facts.append((user_id, fact))
            if len(facts) >= max(1, int(max_facts)):
                break
        return facts

    async def extract(
        self,
        messages: List[dict[str, Any]],
        *,
        api_key: str,
        base_url: str,
        model: str,
        provider: str = "openai_compat",
        extra_headers: Optional[Dict[str, str]] = None,
        max_facts: int = 5,
    ) -> list[tuple[str, str]]:
        rendered = self._render_messages(messages)
        if not rendered or len(rendered) < 8:
            return []

        request_body: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": f"请从以下对话中提取关键事实：\n{rendered}"},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
            "stream": False,
        }

        client: Optional[httpx.AsyncClient] = None
        try:
            client = httpx.AsyncClient(timeout=15.0)
            prepared = build_provider_request(
                provider=provider,
                base_url=base_url,
                model=model,
                api_key=api_key,
                request_body=request_body,
                extra_headers=extra_headers,
                default_temperature=0.1,
            )
            response = await client.post(
                prepared.url,
                headers=prepared.headers,
                params=prepared.params,
                json=prepared.json_body,
            )
            response.raise_for_status()
            payload = response.json()
            if inspect.isawaitable(payload):
                payload = await payload
            assistant_message, _, _, _ = parse_provider_response(provider=provider, data=payload)
            raw_content = str(assistant_message.get("content") or "").strip()
            return self._parse_facts(raw_content, max_facts=max_facts)
        except Exception as exc:
            log.warning(f"[MemoryExtractor] extraction failed: {exc}")
            return []
        finally:
            if client is not None and not client.is_closed:
                await client.aclose()
