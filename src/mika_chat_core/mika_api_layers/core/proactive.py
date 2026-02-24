"""Mika API - proactive helpers.

从 MikaClient 抽离主动发言相关逻辑，保持行为不变。
"""

from __future__ import annotations

import asyncio
import json
import re
import traceback
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx

from ...infra.logging import logger as log
from ...llm.providers import (
    build_provider_request,
    detect_provider_name,
    get_provider_capabilities,
    parse_provider_response,
)
from ...utils.prompt_loader import load_judge_prompt


def extract_json_object(text: str) -> Optional[str]:
    """
    从文本中健壮地提取 JSON 对象（支持嵌套花括号）。

    Args:
        text: 可能包含 JSON 的文本

    Returns:
        提取出的 JSON 字符串，如果未找到则返回 None
    """
    if not text:
        return None

    text = text.strip()
    start_index = text.find("{")
    if start_index == -1:
        return None

    balance = 0
    for i in range(start_index, len(text)):
        char = text[i]
        if char == "{":
            balance += 1
        elif char == "}":
            balance -= 1

        if balance == 0:
            return text[start_index : i + 1]

    return None


def extract_nickname_from_content(content: str) -> Tuple[str, str]:
    """从格式化消息中提取昵称与纯消息内容。"""
    if not content:
        return ("User", "")

    pattern = r"^\[([^\]]+)\]:\s*(.*)$"
    match = re.match(pattern, content, re.DOTALL)
    if match:
        tag = match.group(1)
        pure_content = match.group(2)
        nickname_match = re.match(r"^(.+?)\([^)]{1,64}\)$", tag)
        if nickname_match:
            return (nickname_match.group(1), pure_content)
        return (tag, pure_content)
    return ("User", content)


async def judge_proactive_intent(
    *,
    context_messages: List[Dict[str, Any]],
    heat_level: int,
    plugin_cfg: Any,
    resolve_model_for_task: Callable[[str, Optional[Dict[str, Any]]], str],
    get_api_key: Callable[[], str],
    get_client: Callable[[], Awaitable[httpx.AsyncClient]],
    base_url: str,
    extract_json: Callable[[str], Optional[str]],
    proactive_judge_error_preview_chars: int,
    proactive_judge_raw_content_short_preview_chars: int,
    proactive_judge_raw_content_error_preview_chars: int,
    proactive_judge_server_response_preview_chars: int,
) -> Dict[str, Any]:
    """判断是否需要主动发言。"""
    raw_content = ""
    response: Optional[httpx.Response] = None

    try:
        prompt_config = load_judge_prompt()
        if not isinstance(prompt_config, dict):
            log.warning(
                f"[主动发言判决] 提示词根节点应为 dict，实际为 {type(prompt_config).__name__}，已禁用本次主动发言"
            )
            return {"should_reply": False, "reason": "invalid_prompt_root"}

        judge_config = prompt_config.get("judge_proactive", {})
        if not isinstance(judge_config, dict):
            log.warning(
                f"[主动发言判决] judge_proactive 应为 dict，实际为 {type(judge_config).__name__}，已禁用本次主动发言"
            )
            return {"should_reply": False, "reason": "invalid_judge_prompt"}

        template = judge_config.get("template", "")
        if not isinstance(template, str):
            template = ""
        if not template:
            log.warning("主动发言判决提示词加载失败")
            return {"should_reply": False, "reason": "No prompt"}

        llm_cfg = plugin_cfg.get_llm_config()
        judge_model = resolve_model_for_task("filter", llm_cfg=llm_cfg)
        log.info(f"[主动发言判决] 正使用判决模型: {judge_model}")

        context_str_list: List[str] = []
        collected_images: List[Dict[str, Any]] = []
        for msg in context_messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                text_part = ""
                for item in content:
                    if item.get("type") == "text":
                        text_part += item.get("text", "")
                    elif item.get("type") == "image_url":
                        collected_images.append(item)
                sender, pure_content = extract_nickname_from_content(text_part)
            else:
                sender, pure_content = extract_nickname_from_content(str(content or ""))

            if "nickname" in msg:
                sender = msg["nickname"]
            if msg.get("role") == "assistant":
                sender = "Mika"

            context_str_list.append(f"{sender}: {pure_content}")

        context_text = "\n".join(context_str_list)
        prompt_text = template.format(heat_level=heat_level, context_messages=context_text)
        final_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]

        if collected_images:
            recent_images = collected_images[-plugin_cfg.mika_proactive_judge_max_images :]
            final_content.extend(recent_images)
            log.debug(f"[主动发言判决] 包含图片输入 | count={len(recent_images)}")

        current_api_key = get_api_key()
        messages = [{"role": "user", "content": final_content}]
        provider_name = detect_provider_name(
            configured_provider=str(llm_cfg.get("provider") or "openai_compat"),
            base_url=base_url,
        )
        provider_capabilities = get_provider_capabilities(
            configured_provider=provider_name,
            base_url=base_url,
            model=judge_model,
        )
        extra_headers = dict(llm_cfg.get("extra_headers") or {})

        client = await get_client()
        max_retries = plugin_cfg.mika_proactive_judge_max_retries
        retry_delay = plugin_cfg.mika_proactive_judge_retry_delay_seconds

        for attempt in range(max_retries + 1):
            try:
                request_body: Dict[str, Any] = {
                    "model": judge_model,
                    "messages": messages,
                    "temperature": plugin_cfg.mika_proactive_temperature,
                    "stream": False,
                }
                if provider_capabilities.supports_json_object_response:
                    request_body["response_format"] = {"type": "json_object"}
                prepared = build_provider_request(
                    provider=provider_name,
                    base_url=base_url,
                    model=judge_model,
                    api_key=current_api_key,
                    request_body=request_body,
                    extra_headers=extra_headers,
                    default_temperature=float(plugin_cfg.mika_proactive_temperature),
                )
                response = await client.post(
                    prepared.url,
                    headers=prepared.headers,
                    params=prepared.params,
                    json=prepared.json_body,
                    timeout=plugin_cfg.mika_proactive_judge_timeout_seconds,
                )
                break
            except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException) as exc:
                if attempt < max_retries:
                    log.warning(
                        f"[主动发言判决] 网络错误，第 {attempt + 1} 次重试 | "
                        f"error={type(exc).__name__}: {str(exc)[:proactive_judge_error_preview_chars]}"
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    log.error(
                        f"[主动发言判决] 网络错误，重试 {max_retries} 次后仍失败 | "
                        f"error={type(exc).__name__}: {str(exc)[:proactive_judge_error_preview_chars]}"
                    )
                    return {"should_reply": False, "reason": f"network_error: {type(exc).__name__}"}

        if response is None:
            return {"should_reply": False, "reason": "no_response"}

        response.raise_for_status()
        data = response.json()
        if provider_name == "openai_compat":
            raw_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            finish_reason = data.get("choices", [{}])[0].get("finish_reason", "UNKNOWN")
        else:
            assistant_message, _tool_calls, parsed_content, parsed_finish_reason = parse_provider_response(
                provider=provider_name,
                data=data,
            )
            raw_content = (
                str(parsed_content)
                if parsed_content is not None
                else str(assistant_message.get("content") or "")
            )
            finish_reason = parsed_finish_reason or "UNKNOWN"

        if not raw_content or not raw_content.strip():
            log.warning(f"[主动发言判决] API 返回空内容 | finish_reason={finish_reason} | Full Data: {data}")
            return {"should_reply": False}

        clean_content = re.sub(r"^```(?:json)?\s*", "", raw_content.strip())
        clean_content = re.sub(r"```\s*$", "", clean_content)
        clean_content = clean_content.strip()
        if not clean_content:
            log.warning(
                f"[主动发言判决] 内容清理后为空 | 原始: {raw_content[:proactive_judge_raw_content_short_preview_chars]}"
            )
            return {"should_reply": False}

        extracted_json = extract_json(clean_content)
        if extracted_json:
            clean_content = extracted_json

        result = json.loads(clean_content)
        log.info(f"[主动发言判决] 结果: {result.get('should_reply')}")
        return result

    except json.JSONDecodeError as exc:
        if not raw_content and response is not None:
            try:
                server_response = response.text[:proactive_judge_server_response_preview_chars]
                log.error(
                    f"[主动发言判决] API 响应解析失败 (HTTP {response.status_code}): {exc} | Body: {server_response}"
                )
                return {"should_reply": False}
            except Exception:
                pass

        raw_preview = (
            raw_content[:proactive_judge_raw_content_error_preview_chars]
            if raw_content
            else "(DEBUG_EMPTY_CONTENT)"
        )
        raw_hex = raw_content.encode("utf-8").hex() if raw_content else "None"
        log.error(f"[主动发言判决] JSON 解析失败: {exc} | 原始内容: {raw_preview} | Hex: {raw_hex}")
        return {"should_reply": False}
    except Exception as exc:
        log.error(f"[主动发言判决] 失败: {repr(exc)}")
        log.error(traceback.format_exc())
        return {"should_reply": False}
