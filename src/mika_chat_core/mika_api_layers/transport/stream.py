"""Mika API - 流式传输流程。"""

from __future__ import annotations

import copy
import json
from typing import Any, AsyncIterator, Awaitable, Callable, Dict

import httpx

from ...config import plugin_config
from ...errors import AuthenticationError, MikaAPIError, RateLimitError, ServerError
from ...infra.logging import logger as log
from ...llm.providers import build_provider_request


RETRY_AFTER_DEFAULT_SECONDS = 60
STREAM_HTTP_ERROR_BODY_PREVIEW_CHARS = 500
STREAM_AUTH_ERROR_BODY_PREVIEW_CHARS = 200


async def stream_api_request_flow(
    *,
    http_client: httpx.AsyncClient,
    request_body: Dict[str, Any],
    request_id: str,
    api_key: str,
    base_url: str,
    model: str,
    send_api_request_caller: Callable[..., Awaitable[Any]],
) -> AsyncIterator[str]:
    """发送流式请求，逐段返回文本增量。"""
    llm_cfg = plugin_config.get_llm_config()
    provider_name = str(llm_cfg.get("provider") or "openai_compat")
    extra_headers = dict(llm_cfg.get("extra_headers") or {})
    prepared = build_provider_request(
        provider=provider_name,
        base_url=base_url,
        model=model,
        api_key=api_key,
        request_body=request_body,
        extra_headers=extra_headers,
        default_temperature=float(plugin_config.mika_temperature),
    )
    stream_body = copy.deepcopy(prepared.json_body)
    stream_body["stream"] = True

    if provider_name not in {"openai_compat", "azure_openai"}:
        log.info(
            f"[req:{request_id}] provider={provider_name} 暂未支持原生流式，回退为单次响应"
        )
        message, _tool_calls, _ = await send_api_request_caller(
            http_client=http_client,
            request_body=request_body,
            request_id=request_id,
            retry_count=0,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        text = str(message.get("content") or "")
        if text:
            yield text
        return

    log.info(f"[req:{request_id}] 发送流式请求 | model={model} | provider={provider_name}")
    try:
        async with http_client.stream(
            "POST",
            prepared.url,
            headers=prepared.headers,
            params=prepared.params,
            json=stream_body,
        ) as response:
            status = int(getattr(response, "status_code", 200) or 200)
            if status == 429:
                retry_after = int((getattr(response, "headers", {}) or {}).get("Retry-After", RETRY_AFTER_DEFAULT_SECONDS))
                raise RateLimitError("API rate limit exceeded", status_code=429, retry_after=retry_after)
            if status in {401, 403}:
                body = await response.aread()
                detail = str(body.decode("utf-8", errors="ignore"))[:STREAM_AUTH_ERROR_BODY_PREVIEW_CHARS]
                raise AuthenticationError(
                    f"API authentication failed: {status} ({detail})",
                    status_code=status,
                )
            if status in {500, 502, 503, 504}:
                raise ServerError(f"Server error {status}", status_code=status)
            if status >= 400:
                body = await response.aread()
                detail = str(body.decode("utf-8", errors="ignore"))[:STREAM_HTTP_ERROR_BODY_PREVIEW_CHARS]
                raise MikaAPIError(f"API error: {status} ({detail})", status_code=status)

            saw_tool_calls = False
            emitted = 0
            async for line in response.aiter_lines():
                payload_line = str(line or "").strip()
                if not payload_line.startswith("data:"):
                    continue
                payload = payload_line[5:].strip()
                if not payload:
                    continue
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                except Exception:
                    continue
                choices = data.get("choices") or []
                choice = choices[0] if isinstance(choices, list) and choices else {}
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta") or {}
                if not isinstance(delta, dict):
                    continue
                tool_calls = delta.get("tool_calls")
                if isinstance(tool_calls, list) and tool_calls:
                    saw_tool_calls = True
                content = delta.get("content")
                if isinstance(content, str):
                    text = content
                    if text:
                        emitted += len(text)
                        yield text
                    continue
                if isinstance(content, list):
                    chunks: list[str] = []
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        if str(item.get("type") or "").strip().lower() != "text":
                            continue
                        text = str(item.get("text") or "")
                        if text:
                            chunks.append(text)
                    if chunks:
                        combined = "".join(chunks)
                        emitted += len(combined)
                        yield combined
            if saw_tool_calls:
                log.warning(
                    f"[req:{request_id}] 流式响应包含 tool_calls，流式路径暂不处理工具调用"
                )
            if emitted <= 0:
                log.warning(f"[req:{request_id}] 流式响应未产生文本增量")
    except httpx.TimeoutException as exc:
        raise ServerError(f"stream timeout: {exc}", status_code=408) from exc
