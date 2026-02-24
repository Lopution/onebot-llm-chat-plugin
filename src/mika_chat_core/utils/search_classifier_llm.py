"""搜索分类器 — LLM 主题分类主流程。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import re

from ..infra.logging import logger as log

from ..config import plugin_config
from ..llm.providers import (
    build_provider_request,
    detect_provider_name,
    get_provider_capabilities,
    parse_provider_response,
)

from .search_classifier_cache import (
    CLASSIFY_CONTEXT_ITEM_PREVIEW_CHARS,
    CLASSIFY_HTTP_TIMEOUT_SECONDS,
    CLASSIFY_LOG_BODY_CONTENT_PREVIEW_CHARS,
    CLASSIFY_LOG_MESSAGE_PREVIEW_CHARS,
    CLASSIFY_LOG_RAW_CONTENT_LONG_PREVIEW_CHARS,
    CLASSIFY_LOG_RESPONSE_PREVIEW_CHARS,
    CLASSIFY_LOG_USER_MSG_PREVIEW_CHARS,
    CLASSIFY_PROMPT_DEFAULT,
    MIN_VALID_RESPONSE_LEN,
    MUST_SEARCH_TOPICS,
    PRONOUN_CONTEXT_TAIL_COUNT,
    RESPONSE_FORMAT_DOWNGRADE_ERROR_PREVIEW_CHARS,
    _get_classify_cache_key,
    _get_classify_cache_max_size,
    _get_classify_cache_ttl_seconds,
    _get_classify_max_query_length,
    _get_classify_max_tokens,
    _get_classify_prompt,
    _get_classify_temperature,
    _get_cached_classify_result,
    _get_query_normalize_bot_names,
    _set_classify_cache,
)
from .search_classifier_rules import (
    normalize_search_query,
    _is_overcompressed_query,
    _resolve_pronoun_query,
)
from .search_classifier_parse import _extract_json_object


async def classify_topic_for_search(
    message: str,
    api_key: str,
    base_url: str,
    context: list = None,
    model: str = "gemini-3-flash",
) -> tuple[bool, str, str]:
    """使用 LLM 分析问题，智能判断是否需要搜索并生成优化查询。"""

    import httpx
    import json

    bot_names = _get_query_normalize_bot_names()
    normalized_message = normalize_search_query(message, bot_names=bot_names)

    context_section = ""
    if context and len(context) > 0:
        context_lines = []
        for msg in context[-PRONOUN_CONTEXT_TAIL_COUNT:]:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                short_content = (
                    content[:CLASSIFY_CONTEXT_ITEM_PREVIEW_CHARS] + "..."
                    if len(content) > CLASSIFY_CONTEXT_ITEM_PREVIEW_CHARS
                    else content
                )
                context_lines.append(f"{role}: {short_content}")
        if context_lines:
            context_section = "最近对话历史:\n" + "\n".join(context_lines) + "\n\n"

    current_time = datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.now().year

    classify_prompt = _get_classify_prompt()
    if not classify_prompt:
        log.warning("分类提示词加载失败，使用默认")
        classify_prompt = CLASSIFY_PROMPT_DEFAULT

    prompt = classify_prompt.format(
        context_section=context_section,
        question=normalized_message,
        current_time=current_time,
        current_year=current_year,
    )

    log.debug(
        f"开始智能分类 | message='{message[:CLASSIFY_LOG_MESSAGE_PREVIEW_CHARS]}' | context_len={len(context) if context else 0}"
    )

    cache_key = _get_classify_cache_key(message, context=context)
    cached = _get_cached_classify_result(cache_key, _get_classify_cache_ttl_seconds())
    if cached is not None:
        needs_search, topic, search_query = cached
        log.debug(f"分类判定缓存命中 | needs_search={needs_search} | topic={topic}")
        return needs_search, topic, search_query

    try:
        classify_max_tokens = _get_classify_max_tokens()
        classify_temperature = _get_classify_temperature()
        provider_name = detect_provider_name(
            configured_provider=str(getattr(plugin_config, "llm_provider", "openai_compat")),
            base_url=base_url,
        )
        provider_capabilities = get_provider_capabilities(
            configured_provider=provider_name,
            base_url=base_url,
            model=model,
        )
        log.debug(
            f"[诊断] 分类器参数 | max_tokens={classify_max_tokens} | "
            f"temperature={classify_temperature} | model={model} | provider={provider_name}"
        )

        async with httpx.AsyncClient(timeout=CLASSIFY_HTTP_TIMEOUT_SECONDS) as client:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"请分析以下用户消息并输出 JSON 判定结果：\n{normalized_message}"},
            ]

            request_body = {
                "model": model,
                "messages": messages,
                "stream": False,
                "max_tokens": classify_max_tokens,
                "temperature": classify_temperature,
            }
            if provider_capabilities.supports_json_object_response:
                request_body["response_format"] = {"type": "json_object"}

            log.info(
                f"[分类器请求] model={model} | messages_count={len(messages)} | "
                f"system_len={len(prompt)} | user_msg='{normalized_message[:CLASSIFY_LOG_USER_MSG_PREVIEW_CHARS]}...'"
            )

            def _sanitize_body_for_log(body: dict) -> dict:
                b = dict(body)
                msgs = b.get("messages")
                if isinstance(msgs, list):
                    summarized = []
                    for m in msgs:
                        role = m.get("role") if isinstance(m, dict) else None
                        content = ""
                        if isinstance(m, dict):
                            content = str(m.get("content") or "")
                        summarized.append(
                            {
                                "role": role,
                                "content_len": len(content),
                                "content_preview": (
                                    (content[:CLASSIFY_LOG_BODY_CONTENT_PREVIEW_CHARS] + "...")
                                    if len(content) > CLASSIFY_LOG_BODY_CONTENT_PREVIEW_CHARS
                                    else content
                                ),
                            }
                        )
                    b["messages"] = summarized
                return b

            try:
                log.debug(
                    "分类请求体: %s",
                    json.dumps(_sanitize_body_for_log(request_body), ensure_ascii=False),
                )
            except Exception:
                log.debug(
                    "分类请求体(关键字段): model=%s response_format=%s",
                    request_body.get("model"),
                    request_body.get("response_format"),
                )

            async def _post_classify(body: dict) -> httpx.Response:
                prepared = build_provider_request(
                    provider=provider_name,
                    base_url=base_url,
                    model=model,
                    api_key=api_key,
                    request_body=body,
                    extra_headers=dict(plugin_config.get_llm_config().get("extra_headers") or {}),
                    default_temperature=float(classify_temperature),
                )
                return await client.post(
                    prepared.url,
                    headers=prepared.headers,
                    params=prepared.params,
                    json=prepared.json_body,
                )

            used_response_format = "response_format" in request_body
            did_downgrade = False

            response = await _post_classify(request_body)
            log.debug(f"分类响应状态码: {response.status_code}")

            if (
                response.status_code >= 400
                and response.status_code < 500
                and "response_format" in request_body
            ):
                response_text = (
                    response.text[:RESPONSE_FORMAT_DOWNGRADE_ERROR_PREVIEW_CHARS]
                    if response.text
                    else "无内容"
                )
                log.warning(
                    f"主题分类 response_format 可能不兼容，降级重试 | "
                    f"status={response.status_code} | {response_text}"
                )
                downgraded_body = request_body.copy()
                downgraded_body.pop("response_format", None)
                response = await _post_classify(downgraded_body)
                did_downgrade = True
                log.debug(f"分类响应状态码(降级后): {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                if provider_name == "openai_compat":
                    choice = data.get("choices", [{}])[0]
                    finish_reason = choice.get("finish_reason", "unknown")
                    content = choice.get("message", {}).get("content")
                else:
                    assistant_message, _tool_calls, parsed_content, parsed_finish_reason = parse_provider_response(
                        provider=provider_name,
                        data=data,
                    )
                    finish_reason = parsed_finish_reason or "unknown"
                    content = parsed_content if parsed_content is not None else assistant_message.get("content")
                raw_content = (content or "").strip()

                log.info(
                    f"[分类器响应] finish_reason={finish_reason} | "
                    f"content_len={len(raw_content)} | raw_content='{raw_content[:CLASSIFY_LOG_RESPONSE_PREVIEW_CHARS]}'"
                )

                if finish_reason == "length":
                    log.warning(
                        f"分类响应被 max_tokens 截断 | finish_reason=length | "
                        f"content_len={len(raw_content)} | max_tokens={classify_max_tokens}"
                    )

                log_content = (
                    raw_content[:CLASSIFY_LOG_RAW_CONTENT_LONG_PREVIEW_CHARS] + "..."
                    if len(raw_content) > CLASSIFY_LOG_RAW_CONTENT_LONG_PREVIEW_CHARS
                    else raw_content
                )
                log.debug(f"分类原始响应: {log_content}")

                if not raw_content:
                    log.warning("主题分类返回空内容")
                    return False, "未知", ""

                result = _extract_json_object(raw_content)

                if (not result) and used_response_format and (not did_downgrade):
                    log.warning(
                        "主题分类 JSON mode 可能被忽略/未生效，尝试去除 response_format 再请求一次"
                    )
                    downgraded_body = request_body.copy()
                    downgraded_body.pop("response_format", None)
                    response2 = await _post_classify(downgraded_body)
                    log.debug(f"分类响应状态码(解析失败后降级重试): {response2.status_code}")
                    if response2.status_code == 200:
                        try:
                            data2 = response2.json()
                            if provider_name == "openai_compat":
                                content2 = data2.get("choices", [{}])[0].get("message", {}).get("content")
                            else:
                                assistant_message2, _tool_calls2, parsed_content2, _parsed_finish2 = parse_provider_response(
                                    provider=provider_name,
                                    data=data2,
                                )
                                content2 = (
                                    parsed_content2
                                    if parsed_content2 is not None
                                    else assistant_message2.get("content")
                                )
                            raw_content = (content2 or "").strip()
                            log_content2 = (
                                raw_content[:CLASSIFY_LOG_RAW_CONTENT_LONG_PREVIEW_CHARS] + "..."
                                if len(raw_content) > CLASSIFY_LOG_RAW_CONTENT_LONG_PREVIEW_CHARS
                                else raw_content
                            )
                            log.debug(f"分类原始响应(降级重试): {log_content2}")
                            result = _extract_json_object(raw_content)
                        except Exception as e:
                            log.warning(f"主题分类降级重试解析异常: {type(e).__name__}: {e}")

                if result:
                    needs_search = result.get("needs_search", False)
                    topic = result.get("topic", "未知")
                    search_query = result.get("search_query", "")

                    max_query_len = _get_classify_max_query_length()
                    clean_search_query = normalize_search_query(str(search_query or ""), bot_names=bot_names)
                    clean_search_query = clean_search_query[:max_query_len]

                    if not clean_search_query:
                        log.debug("search_query 为空或清洗后无效，回退到 normalized_message")
                        clean_search_query = (normalized_message or "")[:max_query_len]

                    if needs_search and _is_overcompressed_query(clean_search_query, normalized_message):
                        log.info(
                            "search_query 过度压缩，回退到原问题 | raw_query='%s' | fallback='%s'",
                            clean_search_query,
                            (normalized_message or "")[:80],
                        )
                        clean_search_query = (normalized_message or "")[:max_query_len]

                    if not needs_search:
                        clean_search_query = ""

                    log.success(
                        f"智能分类成功: topic='{topic}' | needs_search={needs_search} | query='{clean_search_query}'"
                    )
                    _set_classify_cache(
                        cache_key,
                        (needs_search, topic, clean_search_query),
                        _get_classify_cache_max_size(),
                    )
                    return needs_search, topic, clean_search_query

                log.warning(
                    f"JSON 提取失败，尝试正则兜底 | raw_len={len(raw_content)} | "
                    f"raw_content='{raw_content}'"
                )

                if len(raw_content) < MIN_VALID_RESPONSE_LEN:
                    log.warning(
                        f"响应过短（{len(raw_content)} < {MIN_VALID_RESPONSE_LEN}），"
                        f"疑似模型输出被截断或异常，采用保守策略"
                    )
                    return False, "响应过短", ""

                needs_search_match = re.search(
                    r'"needs_search"\s*:\s*(true|false)', raw_content, re.IGNORECASE
                )
                if needs_search_match:
                    needs_search_val = needs_search_match.group(1).lower() == "true"

                    query_match = re.search(r'"search_query"\s*:\s*"([^"]*)', raw_content)
                    extracted_query = query_match.group(1) if query_match else ""

                    max_query_len = _get_classify_max_query_length()
                    extracted_query = normalize_search_query(str(extracted_query or ""), bot_names=bot_names)
                    extracted_query = extracted_query[:max_query_len]

                    if len(extracted_query) < 2:
                        extracted_query = (normalized_message or "")[:max_query_len]

                    if needs_search_val and _is_overcompressed_query(extracted_query, normalized_message):
                        log.info(
                            "正则兜底 query 过度压缩，回退到原问题 | raw_query='%s' | fallback='%s'",
                            extracted_query,
                            (normalized_message or "")[:80],
                        )
                        extracted_query = (normalized_message or "")[:max_query_len]

                    extracted_query = _resolve_pronoun_query(extracted_query, context, max_query_len)

                    log.info(
                        f"正则兜底成功: needs_search={needs_search_val} | query='{extracted_query}'"
                    )
                    _set_classify_cache(
                        cache_key,
                        (needs_search_val, "正则提取", extracted_query),
                        _get_classify_cache_max_size(),
                    )
                    return needs_search_val, "正则提取", extracted_query

                log.warning("正则提取失败，回退到关键词匹配")
                needs_search = any(must_topic in raw_content for must_topic in MUST_SEARCH_TOPICS)
                max_query_len = _get_classify_max_query_length()
                result_tuple = (
                    needs_search,
                    "关键词匹配",
                    (normalized_message or "")[:max_query_len],
                )
                _set_classify_cache(cache_key, result_tuple, _get_classify_cache_max_size())
                return result_tuple

            response_text = response.text[:200] if response.text else "无内容"
            log.warning(f"主题分类请求失败: {response.status_code} | {response_text}")
            return False, "未知", ""

    except Exception as e:
        log.warning(f"主题分类异常: {type(e).__name__}: {e}")
        return False, "未知", ""
