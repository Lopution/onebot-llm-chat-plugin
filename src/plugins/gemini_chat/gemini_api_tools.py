"""Gemini API - 工具调用处理逻辑。"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Dict, List, Optional

from nonebot import logger as log
from .metrics import metrics
from .config import plugin_config


async def handle_tool_calls(
    *,
    messages: List[Dict[str, Any]],
    assistant_message: Dict[str, Any],
    tool_calls: List[Dict[str, Any]],
    api_key: str,
    group_id: Optional[str],
    request_id: str,
    tool_handlers: Dict[str, Callable],
    model: str,
    base_url: str,
    http_client,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """处理工具调用并返回最终回复（支持多轮 tool loop）。"""
    max_rounds = max(1, int(getattr(plugin_config, "gemini_tool_max_rounds", 5) or 5))
    tool_timeout = float(getattr(plugin_config, "gemini_tool_timeout_seconds", 20.0) or 20.0)
    force_final = bool(getattr(plugin_config, "gemini_tool_force_final_on_max_rounds", True))

    allowlist = set(getattr(plugin_config, "gemini_tool_allowlist", []) or [])

    current_assistant_message = assistant_message
    current_tool_calls = list(tool_calls or [])

    round_idx = 0
    while current_tool_calls:
        round_idx += 1
        log.info(
            f"[req:{request_id}] 模型请求调用 {len(current_tool_calls)} 个工具 | round={round_idx}/{max_rounds}"
        )
        metrics.tool_calls_total += len(current_tool_calls)

        messages.append(current_assistant_message)

        for tool_call in current_tool_calls:
            function_name = tool_call["function"]["name"]
            function_args = tool_call["function"].get("arguments", "{}")
            tool_call_id = tool_call.get("id", str(uuid.uuid4())[:8])

            log.debug(f"[req:{request_id}] 执行工具: {function_name} | args={function_args}")

            try:
                args = json.loads(function_args) if isinstance(function_args, str) else function_args
            except json.JSONDecodeError:
                args = {"query": function_args}

            tool_result = ""
            if function_name not in allowlist:
                tool_result = f"工具调用被拒绝: {function_name}"
                log.warning(f"[req:{request_id}] 工具未在白名单中: {function_name}")
                metrics.tool_blocked_total += 1
            elif function_name in tool_handlers:
                try:
                    handler = tool_handlers[function_name]
                    if tool_timeout > 0:
                        tool_result = await asyncio.wait_for(
                            handler(args, group_id), timeout=tool_timeout
                        )
                    else:
                        tool_result = await handler(args, group_id)

                    max_chars = max(200, int(plugin_config.gemini_tool_result_max_chars))
                    if len(tool_result) > max_chars:
                        tool_result = tool_result[:max_chars] + "..."
                    log.success(
                        f"[req:{request_id}] 工具 {function_name} 执行成功 | result_len={len(tool_result)}"
                    )
                except asyncio.TimeoutError:
                    tool_result = f"工具执行超时: {function_name}"
                    log.error(f"[req:{request_id}] 工具 {function_name} 执行超时")
                except Exception as e:
                    tool_result = f"工具执行失败: {str(e)}"
                    log.error(f"[req:{request_id}] 工具 {function_name} 执行失败: {e}")
            else:
                tool_result = f"未注册的工具: {function_name}"
                log.warning(f"[req:{request_id}] 未注册的工具: {function_name}")
                metrics.tool_blocked_total += 1

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": tool_result,
                }
            )

        log.debug(f"[req:{request_id}] 发送工具结果，获取下一步回复")
        next_request_body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": getattr(plugin_config, "gemini_temperature", 1.0),
        }
        if tools is not None:
            next_request_body["tools"] = tools

        next_response = await http_client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=next_request_body,
        )
        next_response.raise_for_status()
        next_data = next_response.json()

        choice = (next_data.get("choices") or [{}])[0] or {}
        next_message = (choice.get("message") or {}) if isinstance(choice, dict) else {}
        next_tool_calls = next_message.get("tool_calls") or []

        log.debug(
            f"[req:{request_id}] tool-loop 响应 | "
            f"content_len={len(next_message.get('content') or '')} | "
            f"has_tool_calls={bool(next_tool_calls)} | "
            f"finish_reason={choice.get('finish_reason') or next_data.get('choices', [{}])[0].get('finish_reason')}"
        )

        if next_tool_calls:
            if round_idx >= max_rounds:
                if not force_final:
                    log.warning(
                        f"[req:{request_id}] 工具调用达到上限({max_rounds})，且未启用强制最终答复，直接返回当前 content"
                    )
                    return next_message.get("content") or ""

                log.warning(
                    f"[req:{request_id}] 工具调用达到上限({max_rounds})，强制模型停止使用工具并给出最终答复"
                )
                # 注意：不要把“仍包含 tool_calls 的 assistant message”加入 messages，
                # 否则会产生未对齐的 tool_call/tool_result 对，部分网关会拒绝。
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "工具调用次数已达到上限，请停止使用工具，并根据已经收集到的信息，对你的任务和发现进行总结，然后直接回复用户。"
                        ),
                    }
                )

                final_request_body: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "temperature": getattr(plugin_config, "gemini_temperature", 1.0),
                }
                # 强制最终答复：不再暴露 tools
                final_response = await http_client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=final_request_body,
                )
                final_response.raise_for_status()
                final_data = final_response.json()
                final_message = (
                    (final_data.get("choices") or [{}])[0].get("message", {}) or {}
                )
                return final_message.get("content") or ""

            # 继续下一轮
            current_assistant_message = next_message
            current_tool_calls = list(next_tool_calls)
            continue

        return next_message.get("content") or ""

    # 正常情况下不会到这里（while 条件保证）
    return current_assistant_message.get("content") or ""
