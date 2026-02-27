"""Request planner (heuristic-first, optional LLM mode).

We start with a conservative heuristic planner to improve:
- explainability ("why we replied / used tools / injected memory")
- stability (ability-aware gating, future LLM-planner fallback)

When `mika_planner_mode=llm`, we ask a fast model to output a JSON plan.
When it fails, we always fall back to the heuristic planner.
"""

from __future__ import annotations

from typing import Any, Optional

from .plan_types import MediaNeed, ReplyMode, RequestPlan


def _normalize_policy(value: Any) -> str:
    return str(value or "").strip().lower()


def build_request_plan(
    *,
    plugin_cfg: Any,
    enable_tools: bool,
    is_proactive: bool,
    message: str,
    image_urls_count: int,
    system_injection: Optional[str],
) -> RequestPlan:
    # should_reply:
    # - proactive messages always reply (they are self-triggered).
    # - for normal message, relevance_filter stage may already have stopped upstream.
    should_reply = True

    # tools:
    tool_enabled = bool(enable_tools)
    reply_mode: ReplyMode = "tool_loop" if tool_enabled else "direct"

    # media:
    # - if current request has explicit images, treat as "images".
    # - if system injection already contains caption block, treat as "caption".
    # - else decide by configured default policy.
    policy = _normalize_policy(getattr(plugin_cfg, "mika_media_policy_default", "caption"))
    need_media: MediaNeed = "none"
    if int(image_urls_count or 0) > 0:
        need_media = "images"
    elif isinstance(system_injection, str) and "[Context Media Captions" in system_injection:
        need_media = "caption"
    elif policy in {"caption", "images"}:
        need_media = policy  # type: ignore[assignment]

    use_memory_retrieval = bool(getattr(plugin_cfg, "mika_memory_retrieval_enabled", False))
    use_ltm_memory = (not use_memory_retrieval) and bool(getattr(plugin_cfg, "mika_memory_enabled", False))
    use_knowledge_auto_inject = (not use_memory_retrieval) and bool(
        getattr(plugin_cfg, "mika_knowledge_enabled", False)
    ) and bool(getattr(plugin_cfg, "mika_knowledge_auto_inject", False))

    # tool policy (explain-only; actual allowlist filtering happens later).
    allow = list(getattr(plugin_cfg, "mika_tool_allowlist", []) or [])
    tool_policy = {"enabled": tool_enabled, "allow": allow}

    reason_parts: list[str] = []
    if is_proactive:
        reason_parts.append("proactive")
    if message:
        compact = str(message).strip()
        if len(compact) <= 12:
            reason_parts.append("short_message")
    reason_parts.append(f"tools={'on' if tool_enabled else 'off'}")
    reason_parts.append(f"media={need_media}")
    reason_parts.append(f"retrieval={'on' if use_memory_retrieval else 'off'}")
    if use_ltm_memory:
        reason_parts.append("ltm=on")
    if use_knowledge_auto_inject:
        reason_parts.append("knowledge=on")

    return RequestPlan(
        should_reply=should_reply,
        reply_mode=reply_mode,
        need_media=need_media,
        use_memory_retrieval=use_memory_retrieval,
        use_ltm_memory=use_ltm_memory,
        use_knowledge_auto_inject=use_knowledge_auto_inject,
        tool_policy=tool_policy,
        reason="heuristic:" + ",".join(reason_parts),
        confidence=0.9,
        planner_mode="heuristic",
    )

def _gate_plan_by_config(
    plan: RequestPlan,
    *,
    plugin_cfg: Any,
    enable_tools: bool,
    image_urls_count: int,
    system_injection: Optional[str],
) -> RequestPlan:
    """Never let the planner enable features that are disabled by config gates."""
    # tools gate
    tool_enabled = bool(enable_tools) and bool(plan.tool_policy.get("enabled", False))
    reply_mode: ReplyMode = "tool_loop" if tool_enabled else "direct"
    tool_policy = dict(plan.tool_policy or {})
    tool_policy["enabled"] = tool_enabled

    # retrieval gates
    allow_retrieval = bool(getattr(plugin_cfg, "mika_memory_retrieval_enabled", False))
    allow_ltm = bool(getattr(plugin_cfg, "mika_memory_enabled", False))
    allow_knowledge = bool(getattr(plugin_cfg, "mika_knowledge_enabled", False)) and bool(
        getattr(plugin_cfg, "mika_knowledge_auto_inject", False)
    )

    use_memory_retrieval = bool(plan.use_memory_retrieval) and allow_retrieval
    use_ltm_memory = bool(plan.use_ltm_memory) and allow_ltm and (not use_memory_retrieval)
    use_knowledge_auto_inject = bool(plan.use_knowledge_auto_inject) and allow_knowledge and (not use_memory_retrieval)

    # media gate (plan is currently explain-only, but keep it consistent)
    policy = _normalize_policy(getattr(plugin_cfg, "mika_media_policy_default", "caption"))
    supports_images_override = getattr(plugin_cfg, "mika_llm_supports_images", None)
    need_media: MediaNeed = plan.need_media
    if int(image_urls_count or 0) > 0:
        need_media = "images"
    elif isinstance(system_injection, str) and "[Context Media Captions" in system_injection:
        need_media = "caption"
    elif policy in {"none", "caption", "images"}:
        need_media = policy  # type: ignore[assignment]
    if supports_images_override is False and need_media == "images":
        need_media = "caption" if policy != "none" else "none"

    return RequestPlan(
        should_reply=bool(plan.should_reply),
        reply_mode=reply_mode,
        need_media=need_media,
        use_memory_retrieval=use_memory_retrieval,
        use_ltm_memory=use_ltm_memory,
        use_knowledge_auto_inject=use_knowledge_auto_inject,
        tool_policy=tool_policy,
        reason=str(plan.reason or "").strip() or "llm:unspecified",
        confidence=float(plan.confidence),
        planner_mode=str(plan.planner_mode or "llm"),
    )


async def build_request_plan_async(
    *,
    plugin_cfg: Any,
    enable_tools: bool,
    is_proactive: bool,
    message: str,
    image_urls_count: int,
    system_injection: Optional[str],
) -> RequestPlan:
    """Build a request plan.

    - Heuristic mode: fast, deterministic.
    - LLM mode: ask a fast model for a JSON plan; falls back to heuristic on any failure.
    """
    heuristic = build_request_plan(
        plugin_cfg=plugin_cfg,
        enable_tools=enable_tools,
        is_proactive=is_proactive,
        message=message,
        image_urls_count=image_urls_count,
        system_injection=system_injection,
    )

    try:
        if not bool(getattr(plugin_cfg, "mika_planner_enabled", True)):
            return heuristic
        mode = _normalize_policy(getattr(plugin_cfg, "mika_planner_mode", "heuristic"))
        if mode != "llm":
            return heuristic

        from .llm_planner import plan_with_llm

        planned = await plan_with_llm(
            plugin_cfg=plugin_cfg,
            enable_tools=enable_tools,
            is_proactive=is_proactive,
            message=message,
            image_urls_count=image_urls_count,
            system_injection=system_injection,
        )
        if planned is None:
            return heuristic
        return _gate_plan_by_config(
            planned,
            plugin_cfg=plugin_cfg,
            enable_tools=enable_tools,
            image_urls_count=image_urls_count,
            system_injection=system_injection,
        )
    except Exception:
        return heuristic


__all__ = ["build_request_plan", "build_request_plan_async"]
