"""LLM-based request planner.

The planner produces a json-friendly plan that explains:
- should we reply?
- should we enable tools?
- should we do retrieval/knowledge injection?
- do we need media understanding (none/caption/images)?

This is optional and gated by `mika_planner_mode=llm`.
When it fails, callers must fall back to the heuristic planner.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

from ..llm.providers import build_provider_request, parse_provider_response
from ..mika_api_layers.core.proactive import extract_json_object
from ..utils.context_schema import normalize_content
from .plan_types import MediaNeed, ReplyMode, RequestPlan

log = logging.getLogger(__name__)


_PLAN_SYSTEM_PROMPT = (
    "你是对话请求规划器。你必须只输出一个 JSON 对象，不能输出任何额外文字。\n"
    "字段：should_reply(bool), reply_mode('direct'|'tool_loop'|'no_reply'), "
    "need_media('none'|'caption'|'images'), use_memory_retrieval(bool), use_ltm_memory(bool), "
    "use_knowledge_auto_inject(bool), tool_policy(object: {enabled: bool, allow: [str]}), "
    "reason(str), confidence(float 0~1)。\n"
    "要求：保守、稳定优先；不确定时关闭高风险项（tools/images/retrieval）。"
)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _coerce_float(value: Any, default: float = 0.5) -> float:
    try:
        v = float(value)
        if v != v:  # NaN
            return float(default)
        return max(0.0, min(1.0, v))
    except Exception:
        return float(default)


def _extract_text_from_assistant_message(message: Dict[str, Any]) -> str:
    parsed = normalize_content(message.get("content", ""))
    if isinstance(parsed, str):
        return parsed.strip()
    text_parts: list[str] = []
    for part in parsed or []:
        if not isinstance(part, dict):
            continue
        if str(part.get("type") or "").lower() != "text":
            continue
        value = str(part.get("text") or "").strip()
        if value:
            text_parts.append(value)
    return "\n".join(text_parts).strip()


def _parse_plan_json(raw_text: str) -> Optional[dict[str, Any]]:
    text = str(raw_text or "").strip()
    if not text:
        return None

    extracted = extract_json_object(text)
    if extracted:
        try:
            payload = json.loads(extracted)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            payload = json.loads(match.group(0))
            if isinstance(payload, dict):
                return payload
        except Exception:
            return None
    return None


def _coerce_reply_mode(value: Any, default: ReplyMode = "direct") -> ReplyMode:
    mode = str(value or "").strip().lower()
    if mode in {"direct", "tool_loop", "no_reply"}:
        return mode  # type: ignore[return-value]
    return default


def _coerce_media_need(value: Any, default: MediaNeed = "none") -> MediaNeed:
    mode = str(value or "").strip().lower()
    if mode in {"none", "caption", "images"}:
        return mode  # type: ignore[return-value]
    return default


def _coerce_tool_policy(value: Any, *, enable_tools: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    enabled = _coerce_bool(value.get("enabled"), default=enable_tools)
    allow_raw = value.get("allow")
    allow: list[str] = []
    if isinstance(allow_raw, list):
        for item in allow_raw:
            name = str(item or "").strip()
            if name:
                allow.append(name)
    return {"enabled": bool(enabled) and bool(enable_tools), "allow": allow}


async def plan_with_llm(
    *,
    plugin_cfg: Any,
    enable_tools: bool,
    is_proactive: bool,
    message: str,
    image_urls_count: int,
    system_injection: Optional[str],
) -> Optional[RequestPlan]:
    """Return a plan from LLM, or None on any failure."""
    try:
        llm_cfg = dict(getattr(plugin_cfg, "get_llm_config")())
    except Exception:
        return None

    provider = str(llm_cfg.get("provider") or "openai_compat")
    base_url = str(llm_cfg.get("base_url") or "")
    api_keys = list(llm_cfg.get("api_keys") or [])
    if not api_keys:
        return None

    model = str(getattr(plugin_cfg, "mika_planner_model", "") or "").strip()
    if not model:
        model = str(llm_cfg.get("fast_model") or "").strip()
    if not model:
        model = str(llm_cfg.get("model") or "").strip()
    if not model:
        return None

    timeout_seconds = float(getattr(plugin_cfg, "mika_planner_timeout_seconds", 4.0) or 4.0)
    timeout_seconds = max(1.0, timeout_seconds)

    user_prompt = (
        "[输入]\n"
        f"message={str(message or '').strip()}\n"
        f"is_proactive={1 if bool(is_proactive) else 0}\n"
        f"enable_tools={1 if bool(enable_tools) else 0}\n"
        f"image_urls_count={int(image_urls_count or 0)}\n"
    )
    if system_injection:
        # Keep it short: the planner only needs signals, not full injection content.
        preview = str(system_injection).strip().replace("\n", " ")
        if len(preview) > 240:
            preview = preview[:240] + "..."
        user_prompt += f"\n[system_injection_preview]\n{preview}\n"

    request_body: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 320,
        "stream": False,
    }

    # Try to encourage valid JSON output when provider supports it (best-effort).
    if str(provider or "").strip().lower() in {"openai_compat", "azure_openai"}:
        request_body["response_format"] = {"type": "json_object"}

    prepared = build_provider_request(
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=str(api_keys[0] or ""),
        request_body=request_body,
        extra_headers=dict(llm_cfg.get("extra_headers") or {}),
        default_temperature=0.0,
    )

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(
                prepared.url,
                headers=prepared.headers,
                params=prepared.params,
                json=prepared.json_body,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        status = int(getattr(exc.response, "status_code", 0) or 0)
        body_preview = ""
        try:
            body_preview = str(getattr(exc.response, "text", "") or "").strip().replace("\n", " ")
        except Exception:
            body_preview = ""
        if len(body_preview) > 240:
            body_preview = body_preview[:240] + "..."
        log.warning(
            "planner llm call failed | status=%s | provider=%s | model=%s | body=%r",
            status,
            provider,
            model,
            body_preview,
        )
        return None
    except Exception as exc:
        log.warning(
            "planner llm call failed | provider=%s | model=%s | err_type=%s | err=%r",
            provider,
            model,
            type(exc).__name__,
            exc,
        )
        return None

    try:
        assistant_message, _, _, _ = parse_provider_response(provider=provider, data=data)
        raw_text = _extract_text_from_assistant_message(assistant_message)
        payload = _parse_plan_json(raw_text)
        if not isinstance(payload, dict):
            return None
    except Exception:
        return None

    try:
        should_reply = _coerce_bool(payload.get("should_reply"), default=True)
        reply_mode = _coerce_reply_mode(payload.get("reply_mode"), default="direct")
        need_media = _coerce_media_need(payload.get("need_media"), default="none")
        use_memory_retrieval = _coerce_bool(payload.get("use_memory_retrieval"), default=False)
        use_ltm_memory = _coerce_bool(payload.get("use_ltm_memory"), default=False)
        use_knowledge_auto_inject = _coerce_bool(payload.get("use_knowledge_auto_inject"), default=False)
        tool_policy = _coerce_tool_policy(payload.get("tool_policy"), enable_tools=enable_tools)

        reason = str(payload.get("reason") or "").strip()
        confidence = _coerce_float(payload.get("confidence"), default=0.6)

        # Keep reply_mode consistent with tool_enabled.
        if reply_mode == "tool_loop" and not tool_policy.get("enabled", False):
            reply_mode = "direct"
        if reply_mode != "tool_loop" and tool_policy.get("enabled", False):
            tool_policy["enabled"] = False

        return RequestPlan(
            should_reply=bool(should_reply),
            reply_mode=reply_mode,
            need_media=need_media,
            use_memory_retrieval=bool(use_memory_retrieval),
            use_ltm_memory=bool(use_ltm_memory),
            use_knowledge_auto_inject=bool(use_knowledge_auto_inject),
            tool_policy=tool_policy,
            reason=reason or "llm:unspecified",
            confidence=float(confidence),
            planner_mode="llm",
        )
    except Exception:
        return None


__all__ = ["plan_with_llm"]

