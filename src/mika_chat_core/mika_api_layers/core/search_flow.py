"""Mika API - 搜索前置流程。"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


def estimate_injected_result_count(search_result: str) -> int:
    """估算注入文本中可用结果条数。"""
    if not search_result:
        return 0
    return len(re.findall(r"(?m)^\s*\d+\.\s+", search_result))


def is_presearch_result_insufficient(search_result: str) -> bool:
    """固定规则：预搜索结果是否不足。"""
    if not search_result:
        return False
    result_count = estimate_injected_result_count(search_result)
    if result_count < 2:
        return True
    return len(search_result.strip()) < 360


def normalize_presearch_query(
    message: str,
    *,
    plugin_cfg: Any,
) -> str:
    """预搜索 query 标准化（用于日志和 tool-loop 重复判断）。"""
    from ...utils.search_engine import normalize_search_query

    clean_message = re.sub(r"^\[.*?\]:\s*", "", message).strip()
    clean_message = re.sub(r"@\S+\s*", "", clean_message).strip() or message
    bot_names = [
        getattr(plugin_cfg, "mika_bot_display_name", "") or "",
        getattr(plugin_cfg, "mika_master_name", "") or "",
    ]
    return normalize_search_query(clean_message, bot_names=bot_names)


async def pre_search_raw(
    message: str,
    *,
    enable_tools: bool,
    request_id: str,
    tool_handlers: Dict[str, Any],
    enable_smart_search: bool,
    get_context_async,
    get_api_key,
    base_url: str,
    plugin_cfg: Any,
    log_obj: Any,
    user_id: Optional[str] = None,
    group_id: Optional[str] = None,
) -> str:
    """预执行搜索。"""
    presearch_enabled = bool(getattr(plugin_cfg, "mika_search_presearch_enabled", True))
    if not presearch_enabled:
        log_obj.debug(f"[req:{request_id}] 预搜索总开关关闭，跳过预搜索")
        return ""

    if not enable_tools or not tool_handlers.get("web_search"):
        return ""

    from ...utils.search_engine import (
        classify_topic_for_search,
        is_local_datetime_query,
        is_low_signal_query,
        normalize_search_query,
        serper_search,
        should_fallback_strong_timeliness,
        should_search,
    )

    clean_message = re.sub(r"^\[.*?\]:\s*", "", message).strip()
    clean_message = re.sub(r"@\S+\s*", "", clean_message).strip()
    if not clean_message:
        clean_message = message

    bot_names = [
        getattr(plugin_cfg, "mika_bot_display_name", "") or "",
        getattr(plugin_cfg, "mika_master_name", "") or "",
    ]
    try:
        filter_model = str(plugin_cfg.resolve_task_model("filter")).strip()
    except Exception:
        filter_model = str(getattr(plugin_cfg, "llm_fast_model", "") or "").strip()
    if not filter_model:
        filter_model = str(getattr(plugin_cfg, "llm_model", "") or "").strip()

    normalized_message = normalize_search_query(clean_message, bot_names=bot_names)
    if is_low_signal_query(normalized_message):
        log_obj.debug(f"[req:{request_id}] 低信号消息，跳过预搜索")
        return ""
    if is_local_datetime_query(normalized_message):
        log_obj.debug(f"[req:{request_id}] 本地时间/日期问题，跳过预搜索")
        return ""

    llm_gate_enabled = bool(getattr(plugin_cfg, "mika_search_llm_gate_enabled", False))

    if llm_gate_enabled:
        if not enable_smart_search:
            log_obj.debug(f"[req:{request_id}] LLM gate 开启但 smart_search 未启用，跳过搜索")
            return ""

        context = None
        if user_id:
            try:
                context = await get_context_async(user_id, group_id)
            except Exception as exc:
                log_obj.debug(f"[req:{request_id}] 获取上下文失败，继续 LLM gate | err={exc}")
                context = None

        try:
            needs_search, topic, search_query = await classify_topic_for_search(
                normalized_message,
                api_key=get_api_key(),
                base_url=base_url,
                context=context,
                model=filter_model,
            )
            if needs_search:
                final_query = search_query if search_query else normalized_message
                final_query = normalize_search_query(final_query, bot_names=bot_names)
                final_query = re.sub(r"^\s*\[[^\]]+\]\s*[:：]\s*", "", final_query).strip()
                if is_low_signal_query(final_query):
                    log_obj.debug(f"[req:{request_id}] LLM gate 判定需搜，但 query 低信号，跳过 | topic={topic}")
                    return ""
                if is_local_datetime_query(final_query):
                    log_obj.debug(f"[req:{request_id}] LLM gate 判定需搜，但 query 为本地时间/日期，跳过 | topic={topic}")
                    return ""
                log_obj.info(f"[req:{request_id}] LLM gate 触发搜索 | topic={topic} | query='{final_query}'")
                try:
                    search_result = await serper_search(final_query)
                    if search_result:
                        log_obj.success(
                            f"[req:{request_id}] LLM gate 搜索完成 | topic={topic} | result_len={len(search_result)}"
                        )
                        return search_result
                except Exception as exc:
                    log_obj.warning(f"[req:{request_id}] LLM gate 搜索执行失败: {exc}")
                return ""

            classify_failed = (topic in ("未知", "响应过短") and not (search_query or "").strip())
            log_obj.debug(
                f"[req:{request_id}] [诊断] 分类结果检查 | "
                f"topic='{topic}' | search_query='{search_query}' | classify_failed={classify_failed}"
            )
            if classify_failed:
                fallback_mode = str(
                    getattr(plugin_cfg, "mika_search_llm_gate_fallback_mode", "none") or "none"
                ).strip()
                if fallback_mode == "strong_timeliness" and should_fallback_strong_timeliness(normalized_message):
                    log_obj.info(
                        f"[req:{request_id}] LLM gate 分类失败，强时效回退触发外搜 | "
                        f"topic='{topic}' | msg='{normalized_message[:50]}'"
                    )
                    try:
                        search_result = await serper_search(normalized_message)
                        return search_result or ""
                    except Exception as exc:
                        log_obj.warning(f"[req:{request_id}] LLM gate 强时效回退搜索失败: {exc}")
                log_obj.info(
                    f"[req:{request_id}] LLM gate 分类失败，采用保守策略跳过搜索 | "
                    f"fallback_mode={fallback_mode} | topic='{topic}' | msg='{normalized_message[:50]}'"
                )
            else:
                log_obj.debug(f"[req:{request_id}] LLM gate 判定无需搜索 | topic={topic}")
        except Exception as exc:
            fallback_mode = str(
                getattr(plugin_cfg, "mika_search_llm_gate_fallback_mode", "none") or "none"
            ).strip()
            if fallback_mode == "strong_timeliness" and should_fallback_strong_timeliness(normalized_message):
                log_obj.warning(
                    f"[req:{request_id}] LLM gate 分类异常，强时效回退触发外搜 | "
                    f"error={exc} | msg='{normalized_message[:50]}'"
                )
                try:
                    search_result = await serper_search(normalized_message)
                    return search_result or ""
                except Exception as exc2:
                    log_obj.warning(f"[req:{request_id}] LLM gate 强时效回退搜索失败: {exc2}")
            log_obj.warning(
                f"[req:{request_id}] LLM gate 分类异常，采用保守策略跳过搜索 | "
                f"fallback_mode={fallback_mode} | error={exc} | msg='{normalized_message[:50]}'"
            )
        return ""

    if should_search(normalized_message):
        log_obj.info(f"[req:{request_id}] 关键词触发，预执行搜索")
        try:
            search_result = await serper_search(normalized_message)
            if search_result:
                log_obj.success(f"[req:{request_id}] 预搜索完成 | result_len={len(search_result)}")
                return search_result
        except Exception as exc:
            log_obj.warning(f"[req:{request_id}] 预搜索失败: {exc}")
        return ""

    if enable_smart_search:
        log_obj.debug(f"[req:{request_id}] 关键词未命中，尝试智能搜索分类")
        context = None
        if user_id:
            context = await get_context_async(user_id, group_id)
            log_obj.debug(f"[req:{request_id}] 获取上下文 | count={len(context) if context else 0}")

        try:
            needs_search, topic, search_query = await classify_topic_for_search(
                normalized_message,
                api_key=get_api_key(),
                base_url=base_url,
                context=context,
                model=filter_model,
            )
            if needs_search:
                final_query = search_query if search_query else normalized_message
                final_query = normalize_search_query(final_query, bot_names=bot_names)
                final_query = re.sub(r"^\s*\[[^\]]+\]\s*[:：]\s*", "", final_query).strip()
                if is_low_signal_query(final_query):
                    log_obj.debug(f"[req:{request_id}] 分类 query 低信号，跳过搜索 | topic={topic}")
                    return ""
                if is_local_datetime_query(final_query):
                    log_obj.debug(f"[req:{request_id}] 分类 query 为本地时间/日期，跳过搜索 | topic={topic}")
                    return ""
                log_obj.info(f"[req:{request_id}] 智能分类触发搜索 | topic={topic} | query='{final_query}'")
                try:
                    search_result = await serper_search(final_query)
                    if search_result:
                        log_obj.success(
                            f"[req:{request_id}] 智能搜索完成 | topic={topic} | result_len={len(search_result)}"
                        )
                        return search_result
                except Exception as exc:
                    log_obj.warning(f"[req:{request_id}] 智能搜索执行失败: {exc}")
            else:
                log_obj.debug(f"[req:{request_id}] 智能分类判断无需搜索 | topic={topic}")
        except Exception as exc:
            log_obj.warning(f"[req:{request_id}] 智能搜索分类失败，降级处理: {exc}")

    return ""
