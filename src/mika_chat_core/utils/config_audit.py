"""Config audit helpers.

This module provides *best-effort* checks to surface risky or conflicting
configuration combinations. It must never block startup; callers should treat
the results as warnings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, List


@dataclass(frozen=True)
class ConfigAuditItem:
    level: str  # "warning" | "info"
    code: str
    message: str
    hint: str = ""

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        # Keep json-friendly and stable.
        data["level"] = str(data.get("level") or "warning")
        data["code"] = str(data.get("code") or "")
        data["message"] = str(data.get("message") or "")
        data["hint"] = str(data.get("hint") or "")
        return data  # type: ignore[return-value]


def _norm_str(value: Any) -> str:
    return str(value or "").strip().lower()


def audit_config(cfg: Any) -> List[ConfigAuditItem]:
    """Return a list of warnings for the given config object."""
    items: list[ConfigAuditItem] = []

    try:
        context_mode = _norm_str(getattr(cfg, "mika_context_mode", "structured"))
        if context_mode == "legacy":
            items.append(
                ConfigAuditItem(
                    level="warning",
                    code="context_mode_legacy",
                    message="当前使用 legacy 上下文模式，群聊 working set/transcript 裁剪可能不生效或效果变差。",
                    hint="建议改为 MIKA_CONTEXT_MODE=structured（稳定优先）。",
                )
            )
    except Exception:
        pass

    try:
        max_tokens = int(getattr(cfg, "mika_context_max_tokens_soft", 0) or 0)
        max_bytes = int(getattr(cfg, "mika_request_body_max_bytes", 0) or 0)
        if max_tokens >= 200_000 and 0 < max_bytes < 1_200_000:
            items.append(
                ConfigAuditItem(
                    level="warning",
                    code="budget_tokens_bytes_mismatch",
                    message="token 预算很大但 request body bytes 上限较小，代理/中转更容易出现 HTTP 200 但 content 为空。",
                    hint="可适当降低 MIKA_CONTEXT_MAX_TOKENS_SOFT 或提高 MIKA_REQUEST_BODY_MAX_BYTES。",
                )
            )
    except Exception:
        pass

    try:
        media_policy = _norm_str(getattr(cfg, "mika_media_policy_default", "caption"))
        if media_policy == "images":
            items.append(
                ConfigAuditItem(
                    level="warning",
                    code="media_policy_images",
                    message="当前默认策略为 images：会更容易塞 base64 导致请求体过大/中转不兼容。",
                    hint="更推荐使用 MIKA_MEDIA_POLICY_DEFAULT=caption（像 AstrBot：先语义化）。",
                )
            )

        supports_images = getattr(cfg, "mika_llm_supports_images", None)
        if supports_images is False and media_policy == "images":
            items.append(
                ConfigAuditItem(
                    level="warning",
                    code="supports_images_conflict",
                    message="你声明主上游不支持图片输入，但 media 默认策略仍是 images。",
                    hint="建议设 MIKA_MEDIA_POLICY_DEFAULT=caption 或把 MIKA_LLM_SUPPORTS_IMAGES 设为 true/留空。",
                )
            )
    except Exception:
        pass

    try:
        presearch_enabled = bool(getattr(cfg, "mika_search_presearch_enabled", False))
        if presearch_enabled:
            provider = _norm_str(getattr(cfg, "search_provider", "serper"))
            api_key = str(getattr(cfg, "search_api_key", "") or "").strip()
            if provider in {"serper", "tavily"} and not api_key:
                items.append(
                    ConfigAuditItem(
                        level="warning",
                        code="search_presearch_no_api_key",
                        message="预搜索已开启，但未配置 search_api_key，外置搜索大概率无法工作。",
                        hint="配置 SEARCH_API_KEY 或关闭 MIKA_SEARCH_PRESEARCH_ENABLED。",
                    )
                )
    except Exception:
        pass

    try:
        supports_tools = getattr(cfg, "mika_llm_supports_tools", None)
        allowlist = list(getattr(cfg, "mika_tool_allowlist", []) or [])
        if supports_tools is False and allowlist:
            items.append(
                ConfigAuditItem(
                    level="info",
                    code="supports_tools_off",
                    message="你声明主上游不支持 tools，工具 allowlist 将不会下发到模型。",
                    hint="这是正常的降级行为；如上游实际支持 tools，可设 MIKA_LLM_SUPPORTS_TOOLS=true/留空。",
                )
            )
    except Exception:
        pass

    try:
        stream_enabled = bool(getattr(cfg, "mika_reply_stream_enabled", False))
        split_enabled = bool(getattr(cfg, "mika_message_split_enabled", False))
        if stream_enabled and split_enabled:
            items.append(
                ConfigAuditItem(
                    level="warning",
                    code="stream_split_conflict",
                    message="同时开启了流式与长回复分段，部分平台会出现“分句怪/断行怪/重复发送”等体验问题。",
                    hint="建议先只开一个：MIKA_REPLY_STREAM_ENABLED 或 MIKA_MESSAGE_SPLIT_ENABLED。",
                )
            )
    except Exception:
        pass

    try:
        self_heal = bool(getattr(cfg, "mika_transport_self_heal_enabled", True))
        if not self_heal:
            items.append(
                ConfigAuditItem(
                    level="info",
                    code="self_heal_disabled",
                    message="传输层自愈已关闭：遇到空回复/请求过大会更容易直接失败。",
                    hint="稳定优先建议开启：MIKA_TRANSPORT_SELF_HEAL_ENABLED=true。",
                )
            )
    except Exception:
        pass

    try:
        planner_mode = _norm_str(getattr(cfg, "mika_planner_mode", "heuristic"))
        if planner_mode == "llm":
            items.append(
                ConfigAuditItem(
                    level="info",
                    code="planner_llm_mode",
                    message="planner_mode=llm：每次请求可能会额外调用一次 fast model 来产出结构化 plan。",
                    hint="如更偏稳定/省成本，可改回 MIKA_PLANNER_MODE=heuristic。",
                )
            )
    except Exception:
        pass

    return items


__all__ = ["ConfigAuditItem", "audit_config"]

