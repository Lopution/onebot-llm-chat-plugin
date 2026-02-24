"""Mika API - 传输层兼容门面。"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Optional, Tuple

import httpx

from ...config import plugin_config
from .completion import send_api_request_flow
from .stream import stream_api_request_flow


async def send_api_request(
    *,
    http_client: httpx.AsyncClient,
    request_body: Dict[str, Any],
    request_id: str,
    retry_count: int,
    api_key: str,
    base_url: str,
    model: str,
) -> Tuple[Dict[str, Any], Optional[list], str]:
    """发送 API 请求并处理响应，返回 (assistant_message, tool_calls, api_key)。"""
    return await send_api_request_flow(
        http_client=http_client,
        request_body=request_body,
        request_id=request_id,
        retry_count=retry_count,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )


async def stream_api_request(
    *,
    http_client: httpx.AsyncClient,
    request_body: Dict[str, Any],
    request_id: str,
    api_key: str,
    base_url: str,
    model: str,
) -> AsyncIterator[str]:
    """发送流式请求，逐段返回文本增量。"""
    async for chunk in stream_api_request_flow(
        http_client=http_client,
        request_body=request_body,
        request_id=request_id,
        api_key=api_key,
        base_url=base_url,
        model=model,
        send_api_request_caller=send_api_request,
    ):
        if chunk:
            yield str(chunk)
