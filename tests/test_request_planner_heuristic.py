from __future__ import annotations

from types import SimpleNamespace


def test_build_request_plan_heuristic_basic():
    from mika_chat_core.planning.planner import build_request_plan

    cfg = SimpleNamespace(
        mika_media_policy_default="caption",
        mika_memory_retrieval_enabled=False,
        mika_memory_enabled=True,
        mika_knowledge_enabled=True,
        mika_knowledge_auto_inject=True,
        mika_tool_allowlist=["web_search"],
    )

    plan = build_request_plan(
        plugin_cfg=cfg,
        enable_tools=True,
        is_proactive=False,
        message="?",
        image_urls_count=0,
        system_injection=None,
    )

    assert plan.should_reply is True
    assert plan.reply_mode == "tool_loop"
    assert plan.need_media == "caption"
    assert plan.use_memory_retrieval is False
    assert plan.use_ltm_memory is True
    assert plan.use_knowledge_auto_inject is True
    assert plan.tool_policy["enabled"] is True
    assert "web_search" in plan.tool_policy["allow"]


def test_build_request_plan_explicit_images_overrides_policy():
    from mika_chat_core.planning.planner import build_request_plan

    cfg = SimpleNamespace(mika_media_policy_default="none")
    plan = build_request_plan(
        plugin_cfg=cfg,
        enable_tools=False,
        is_proactive=False,
        message="看这个",
        image_urls_count=1,
        system_injection=None,
    )
    assert plan.need_media == "images"
    assert plan.reply_mode == "direct"
