"""Mika API 消息构建阶段函数。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple, Union

from ...utils.media_semantics import build_media_semantic, placeholder_from_media_semantic


def guard_inputs(
    *,
    message: str,
    search_result: str,
    plugin_cfg: Any,
    log_obj: Any,
    guard_untrusted_text_fn,
) -> Tuple[str, str]:
    guard_enabled = bool(getattr(plugin_cfg, "mika_prompt_injection_guard_enabled", True))
    guard_action = str(
        getattr(plugin_cfg, "mika_prompt_injection_guard_action", "annotate") or "annotate"
    ).strip().lower()
    guard_patterns = list(getattr(plugin_cfg, "mika_prompt_injection_guard_patterns", []) or [])

    guarded_user_message = guard_untrusted_text_fn(
        message,
        source="user_message",
        enabled=guard_enabled,
        action=guard_action,
        custom_patterns=guard_patterns,
    )
    if guarded_user_message.detected:
        log_obj.warning(
            f"检测到潜在提示词注入(user_message) | action={guarded_user_message.action} | "
            f"hits={len(guarded_user_message.matches)}"
        )

    guarded_search_result = guard_untrusted_text_fn(
        search_result,
        source="search_result",
        enabled=guard_enabled,
        action=guard_action,
        custom_patterns=guard_patterns,
    )
    if guarded_search_result.detected:
        log_obj.warning(
            f"检测到潜在提示词注入(search_result) | action={guarded_search_result.action} | "
            f"hits={len(guarded_search_result.matches)}"
        )

    return guarded_user_message.text, guarded_search_result.text


async def build_original_and_api_content(
    *,
    message: str,
    normalized_image_urls: List[str],
    allow_images_in_api: bool,
    has_image_processor: bool,
    get_image_processor,
    plugin_cfg: Any,
    log_obj: Any,
) -> Tuple[Union[str, List[Dict[str, Any]]], Union[str, List[Dict[str, Any]]]]:
    if not normalized_image_urls:
        return message, message

    original_content: Union[str, List[Dict[str, Any]]] = [{"type": "text", "text": message}]
    api_content_list: List[Dict[str, Any]] = [{"type": "text", "text": message}]
    for url in normalized_image_urls:
        url_str = str(url or "").strip()
        semantic = build_media_semantic(kind="image", url=url_str, source="request_image")
        placeholder = placeholder_from_media_semantic(semantic)
        if url_str.startswith(("http://", "https://", "data:")):
            original_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": url_str},
                    "mika_media": semantic,
                }
            )
        else:
            original_content.append({"type": "text", "text": placeholder})
            api_content_list.append({"type": "text", "text": placeholder})
            continue

        if not allow_images_in_api:
            api_content_list.append({"type": "text", "text": placeholder})
            continue

    if not allow_images_in_api:
        return original_content, api_content_list

    data_urls = [url for url in normalized_image_urls if url.startswith("data:")]
    normal_urls = [url for url in normalized_image_urls if not url.startswith("data:")]
    for data_url in data_urls:
        try:
            header, _ = data_url.split(",", 1)
            mime_type = header.split(":")[1].split(";")[0]
            api_content_list.append({"type": "image_url", "image_url": {"url": data_url}})
            log_obj.debug(f"已添加 data URL 图片 | mime={mime_type}")
        except Exception as parse_exc:
            log_obj.warning(f"解析 data URL 失败: {parse_exc}")
    if normal_urls:
        if has_image_processor:
            try:
                processor = get_image_processor(plugin_cfg.mika_image_download_concurrency)
                images_data = await processor.process_images(normal_urls)
                api_content_list.extend(images_data)
                log_obj.debug(f"已处理 {len(images_data)} 张图片")
            except Exception as process_exc:
                log_obj.warning(f"图片处理失败，回退到原始 URL: {process_exc}")
                for url in normal_urls:
                    api_content_list.append({"type": "image_url", "image_url": {"url": url}})
        else:
            for url in normal_urls:
                api_content_list.append({"type": "image_url", "image_url": {"url": url}})
    return original_content, api_content_list


async def build_enhanced_system_prompt(
    *,
    system_prompt: str,
    user_id: str,
    has_user_profile: bool,
    use_persistent: bool,
    get_user_profile_store,
    plugin_cfg: Any,
    log_obj: Any,
    current_time_display: str,
    load_react_prompt_fn,
) -> str:
    enhanced_system_prompt = system_prompt
    if has_user_profile and use_persistent:
        try:
            profile_store = get_user_profile_store()
            user_summary = await profile_store.get_profile_summary(user_id)
            if user_summary:
                enhanced_system_prompt = (
                    f"{system_prompt}\n\n"
                    f"[用户档案 - 请记住这些信息]\n{user_summary}"
                )
                log_obj.debug(f"已注入用户档案 | user={user_id} | summary_len={len(user_summary)}")
        except Exception as exc:
            log_obj.warning(f"获取用户档案失败: {exc}")

    log_obj.debug(f"[时间注入] 当前时间: {current_time_display}")
    enhanced_system_prompt = (
        f"{enhanced_system_prompt}\n\n"
        f"[System Environment]\n"
        f"Current Time: {current_time_display}"
    )

    if bool(getattr(plugin_cfg, "mika_react_enabled", False)):
        react_cfg = load_react_prompt_fn()
        react_suffix = str(react_cfg.get("react_system_suffix") or "").strip()
        if react_suffix:
            enhanced_system_prompt = f"{enhanced_system_prompt}\n\n{react_suffix}"
            log_obj.debug("ReAct system suffix 已注入")
    return enhanced_system_prompt


async def append_history_messages(
    *,
    messages: List[Dict[str, Any]],
    user_id: str,
    group_id: Optional[str],
    history_override: Optional[List[Dict[str, Any]]],
    get_context_async,
    context_level: int,
    use_persistent: bool,
    context_store,
    plugin_cfg: Any,
    supports_images: bool,
    supports_tools: bool,
    normalize_content_fn,
    sanitize_history_message_for_request_fn,
    log_obj: Any,
) -> Tuple[List[Dict[str, Any]], int, int]:
    resolved_group_id = str(group_id or "").strip()

    # Group chat: build a compact transcript from message_archive (working set).
    # This avoids blindly sending the whole structured snapshot upstream, which
    # often leads to HTTP 200 but empty content on proxy endpoints.
    if resolved_group_id:
        try:
            from ...utils.context_db import get_db
            from ...utils.context_store.session_queries import get_recent_archive_messages
            from ...utils.transcript_builder import (
                build_participants_line,
                build_transcript_block,
                build_transcript_lines,
            )

            bot_name = str(getattr(plugin_cfg, "mika_bot_display_name", "Mika") or "Mika").strip() or "Mika"
            max_lines = int(getattr(plugin_cfg, "mika_proactive_chatroom_history_lines", 300) or 300)
            line_max_chars = int(getattr(plugin_cfg, "mika_chatroom_transcript_line_max_chars", 240) or 240)

            # Business-level context degradation keeps working: shrink transcript working set.
            if int(context_level or 0) >= 2:
                max_lines = max(20, int(max_lines * 0.3))
            elif int(context_level or 0) == 1:
                max_lines = max(50, int(max_lines * 0.7))

            if history_override is not None:
                history = list(history_override)
            else:
                history = await get_recent_archive_messages(
                    f"group:{resolved_group_id}",
                    limit=max(1, max_lines * 2),
                    get_db_fn=get_db,
                    log_obj=log_obj,
                )

            lines = build_transcript_lines(
                history,
                bot_name=bot_name,
                max_lines=max(0, max_lines),
                line_max_chars=line_max_chars,
            )
            participants_line = build_participants_line(lines, bot_name=bot_name)
            if participants_line:
                lines = [participants_line, *lines]
            block = build_transcript_block(lines)
            messages.append({"role": "system", "content": block.text})
        except Exception as exc:
            log_obj.debug(f"group transcript build failed, fallback to structured history: {exc}")
        else:
            return messages, 0, 0

    history = (await get_context_async(user_id, group_id) if history_override is None else list(history_override))
    dropped_tool_messages = 0
    dropped_unsupported_images = 0

    if context_level > 0:
        context_limits = {1: 20, 2: 5}
        limit = context_limits.get(context_level, 5)
        original_count = len(history)
        history = history[-limit:] if len(history) > limit else history

        if use_persistent and context_store:
            history = await context_store.compress_context_for_safety(history, level=context_level)
            log_obj.warning(
                f"[上下文降级+安全压缩] Level {context_level} | "
                f"截断: {original_count} -> {len(history)} 条 | 已应用敏感词替换"
            )
        elif original_count > len(history):
            log_obj.warning(
                f"[上下文降级] Level {context_level} | 截断: {original_count} -> {len(history)} 条"
            )

    current_time = time.time()
    for raw_msg in history:
        raw_role = str(raw_msg.get("role") or "").strip().lower()
        if raw_role == "tool" and not supports_tools:
            dropped_tool_messages += 1
            continue
        raw_content = normalize_content_fn(raw_msg.get("content", ""))
        if not supports_images and isinstance(raw_content, list):
            dropped_unsupported_images += sum(
                1
                for part in raw_content
                if isinstance(part, dict) and str(part.get("type") or "").lower() == "image_url"
            )

        sanitized = sanitize_history_message_for_request_fn(
            raw_msg,
            allow_images=supports_images,
            allow_tools=supports_tools,
            normalize_content_fn=normalize_content_fn,
        )
        if not sanitized:
            continue

        role = sanitized.get("role")
        content = sanitized.get("content")
        msg_id = sanitized.get("message_id")
        if (
            msg_id
            and isinstance(content, str)
            and "<msg_id:" not in content
            and ("[图片" in content or "[表情" in content)
        ):
            content = f"{content} <msg_id:{msg_id}>"

        msg_timestamp = 0.0
        try:
            msg_timestamp = float(sanitized.get("timestamp", 0) or 0)
        except (TypeError, ValueError):
            msg_timestamp = 0.0

        if msg_timestamp > 0:
            time_diff = current_time - msg_timestamp
            time_hint = ""
            if time_diff < 60:
                time_hint = ""
            elif time_diff < 300:
                time_hint = "[几分钟前] "
            elif time_diff < 1800:
                time_hint = "[半小时前] "
            elif time_diff < 3600:
                time_hint = "[约1小时前] "
            elif time_diff < 7200:
                time_hint = "[1-2小时前] "
            elif time_diff < 86400:
                time_hint = f"[约{int(time_diff / 3600)}小时前] "
            else:
                time_hint = f"[{int(time_diff / 86400)}天前] "

            if time_hint:
                if isinstance(content, str):
                    content = f"{time_hint}{content}"
                elif isinstance(content, list):
                    content = [{"type": "text", "text": time_hint.strip()}] + content

        out_msg: Dict[str, Any] = {"role": role, "content": content}
        if role == "assistant" and isinstance(sanitized.get("tool_calls"), list):
            out_msg["tool_calls"] = sanitized["tool_calls"]
        if role == "tool" and sanitized.get("tool_call_id"):
            out_msg["tool_call_id"] = sanitized["tool_call_id"]
        messages.append(out_msg)
    return messages, dropped_tool_messages, dropped_unsupported_images


def filter_tools_for_request(
    *,
    available_tools: List[Dict[str, Any]],
    search_result: str,
    plugin_cfg: Any,
    build_effective_allowlist_fn,
    is_presearch_result_insufficient_fn,
    estimate_injected_result_count_fn,
    log_obj: Any,
) -> Tuple[List[Dict[str, Any]], bool]:
    presearch_hit = bool((search_result or "").strip())
    allow_refine = bool(
        presearch_hit
        and is_presearch_result_insufficient_fn(search_result)
        and bool(getattr(plugin_cfg, "mika_search_allow_tool_refine", True))
    )
    filtered_tools: List[Dict[str, Any]] = []
    try:
        allowlist = build_effective_allowlist_fn(
            getattr(plugin_cfg, "mika_tool_allowlist", []),
            include_dynamic_sources=bool(
                getattr(plugin_cfg, "mika_tool_allow_dynamic_registered", True)
            ),
        )
        if allowlist:
            for tool in (available_tools or []):
                if not isinstance(tool, dict):
                    continue
                if tool.get("type") == "function":
                    fn = tool.get("function") or {}
                    name = fn.get("name") if isinstance(fn, dict) else None
                    if name == "web_search" and presearch_hit and not allow_refine:
                        continue
                    if name in allowlist:
                        filtered_tools.append(tool)
                else:
                    filtered_tools.append(tool)
        else:
            for tool in (available_tools or []):
                if isinstance(tool, dict) and tool.get("type") != "function":
                    filtered_tools.append(tool)
    except Exception as exc:
        log_obj.warning(f"tools allowlist 过滤失败，回退原工具列表: {exc}")
        filtered_tools = list(available_tools) if available_tools else []

    if presearch_hit:
        log_obj.info(
            "search_decision "
            f"presearch_hit=1 allow_refine={1 if allow_refine else 0} "
            f"result_count={estimate_injected_result_count_fn(search_result)} "
            f"tool_web_search_exposed="
            f"{1 if any((tool.get('function') or {}).get('name') == 'web_search' for tool in filtered_tools if isinstance(tool, dict) and tool.get('type') == 'function') else 0}"
        )
    return filtered_tools, presearch_hit
