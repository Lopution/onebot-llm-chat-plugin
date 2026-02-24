"""Mika API - 消息构建与搜索前置逻辑（门面层）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from ...config import plugin_config
from ...infra.logging import logger as log
from ...llm.providers import get_provider_capabilities
from ..builder.flow import (
    build_messages_flow as service_build_messages_flow,
    normalize_image_inputs as service_normalize_image_inputs,
    sanitize_content_for_request as service_sanitize_content_for_request,
    sanitize_history_message_for_request as service_sanitize_history_message_for_request,
)
from .search_flow import (
    estimate_injected_result_count as service_estimate_injected_result_count,
    is_presearch_result_insufficient as service_is_presearch_result_insufficient,
    normalize_presearch_query as service_normalize_presearch_query,
    pre_search_raw as service_pre_search_raw,
)
from ...security.prompt_injection import guard_untrusted_text
from ...tools_registry import build_effective_allowlist
from ...utils.context_schema import normalize_content
from ...utils.prompt_loader import load_react_prompt


@dataclass
class MessageBuildResult:
    """消息构建结果容器。"""

    messages: List[Dict[str, Any]]
    original_content: Union[str, List[Dict[str, Any]]]
    api_content: Union[str, List[Dict[str, Any]]]
    request_body: Dict[str, Any]


@dataclass
class PreSearchResult:
    """预搜索结构化结果。"""

    search_result: str
    normalized_query: str
    presearch_hit: bool
    allow_tool_refine: bool
    result_count: int
    refine_rounds_used: int = 0
    blocked_duplicate_total: int = 0
    decision: str = "unknown"


def _estimate_injected_result_count(search_result: str) -> int:
    return service_estimate_injected_result_count(search_result)


def _is_presearch_result_insufficient(search_result: str) -> bool:
    return service_is_presearch_result_insufficient(search_result)


def _build_pre_search_result(
    *,
    search_result: str,
    normalized_query: str,
    decision: str,
) -> PreSearchResult:
    presearch_hit = bool((search_result or "").strip())
    result_count = _estimate_injected_result_count(search_result)
    insufficient = _is_presearch_result_insufficient(search_result)
    allow_tool_refine = bool(
        presearch_hit
        and insufficient
        and bool(getattr(plugin_config, "mika_search_allow_tool_refine", True))
    )
    return PreSearchResult(
        search_result=search_result or "",
        normalized_query=normalized_query or "",
        presearch_hit=presearch_hit,
        allow_tool_refine=allow_tool_refine,
        result_count=result_count,
        decision=decision,
    )


def _sanitize_content_for_request(content: Any, *, allow_images: bool) -> Union[str, List[Dict[str, Any]]]:
    return service_sanitize_content_for_request(
        content,
        allow_images=allow_images,
        normalize_content_fn=normalize_content,
    )


def _sanitize_history_message_for_request(
    raw_msg: Dict[str, Any],
    *,
    allow_images: bool,
    allow_tools: bool,
) -> Optional[Dict[str, Any]]:
    return service_sanitize_history_message_for_request(
        raw_msg,
        allow_images=allow_images,
        allow_tools=allow_tools,
        normalize_content_fn=normalize_content,
    )


def _normalize_image_inputs(
    image_urls: Optional[List[str]],
    *,
    max_images: int,
) -> List[str]:
    return service_normalize_image_inputs(image_urls, max_images=max_images)


async def _pre_search_raw(
    message: str,
    *,
    enable_tools: bool,
    request_id: str,
    tool_handlers: Dict[str, Any],
    enable_smart_search: bool,
    get_context_async,
    get_api_key,
    base_url: str,
    user_id: Optional[str] = None,
    group_id: Optional[str] = None,
) -> str:
    return await service_pre_search_raw(
        message,
        enable_tools=enable_tools,
        request_id=request_id,
        tool_handlers=tool_handlers,
        enable_smart_search=enable_smart_search,
        get_context_async=get_context_async,
        get_api_key=get_api_key,
        base_url=base_url,
        plugin_cfg=plugin_config,
        log_obj=log,
        user_id=user_id,
        group_id=group_id,
    )


async def pre_search(
    message: str,
    *,
    enable_tools: bool,
    request_id: str,
    tool_handlers: Dict[str, Any],
    enable_smart_search: bool,
    get_context_async,
    get_api_key,
    base_url: str,
    user_id: Optional[str] = None,
    group_id: Optional[str] = None,
    return_meta: bool = False,
) -> Union[str, PreSearchResult]:
    """预执行搜索。

    - `return_meta=False`：保持兼容，仅返回搜索注入文本（str）。
    - `return_meta=True`：返回结构化结果，用于搜索链路收敛编排。
    """
    search_result = await _pre_search_raw(
        message,
        enable_tools=enable_tools,
        request_id=request_id,
        tool_handlers=tool_handlers,
        enable_smart_search=enable_smart_search,
        get_context_async=get_context_async,
        get_api_key=get_api_key,
        base_url=base_url,
        user_id=user_id,
        group_id=group_id,
    )
    if not return_meta:
        return search_result

    normalized_query = service_normalize_presearch_query(
        message,
        plugin_cfg=plugin_config,
    )
    return _build_pre_search_result(
        search_result=search_result,
        normalized_query=normalized_query,
        decision="presearch_hit" if search_result else "presearch_miss",
    )


async def build_messages(
    message: str,
    *,
    user_id: str,
    group_id: Optional[str],
    image_urls: Optional[List[str]],
    search_result: str,
    model: str,
    system_prompt: str,
    available_tools: List[Dict[str, Any]],
    system_injection: Optional[str],
    context_level: int,
    history_override: Optional[List[Dict[str, Any]]] = None,
    get_context_async=None,
    use_persistent: bool = False,
    context_store=None,
    has_image_processor: bool = False,
    get_image_processor=None,
    has_user_profile: bool = False,
    get_user_profile_store=None,
    enable_tools: bool = True,
) -> MessageBuildResult:
    """构建消息历史与请求体。"""
    result = await service_build_messages_flow(
        message,
        user_id=user_id,
        group_id=group_id,
        image_urls=image_urls,
        search_result=search_result,
        model=model,
        system_prompt=system_prompt,
        available_tools=available_tools,
        system_injection=system_injection,
        context_level=context_level,
        history_override=history_override,
        get_context_async=get_context_async,
        use_persistent=use_persistent,
        context_store=context_store,
        has_image_processor=has_image_processor,
        get_image_processor=get_image_processor,
        has_user_profile=has_user_profile,
        get_user_profile_store=get_user_profile_store,
        enable_tools=enable_tools,
        plugin_cfg=plugin_config,
        log_obj=log,
        guard_untrusted_text_fn=guard_untrusted_text,
        get_provider_capabilities_fn=get_provider_capabilities,
        build_effective_allowlist_fn=build_effective_allowlist,
        load_react_prompt_fn=load_react_prompt,
        normalize_content_fn=normalize_content,
        estimate_injected_result_count_fn=_estimate_injected_result_count,
        is_presearch_result_insufficient_fn=_is_presearch_result_insufficient,
    )
    return MessageBuildResult(
        messages=result["messages"],
        original_content=result["original_content"],
        api_content=result["api_content"],
        request_body=result["request_body"],
    )
