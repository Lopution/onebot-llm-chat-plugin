from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_llm_planner_success_uses_llm_plan(valid_api_key: str):
    from mika_chat_core.config import Config
    from mika_chat_core.planning.plan_types import RequestPlan
    from mika_chat_core.planning.planner import build_request_plan_async

    cfg = Config(
        llm_api_key=valid_api_key,
        mika_master_id=123456789,
        mika_planner_mode="llm",
        mika_planner_enabled=True,
        mika_memory_retrieval_enabled=False,  # gate off: llm plan should not be able to enable it
    )

    llm_plan = RequestPlan(
        should_reply=True,
        reply_mode="tool_loop",
        need_media="none",
        use_memory_retrieval=True,  # should be gated off by config
        use_ltm_memory=True,
        use_knowledge_auto_inject=True,
        tool_policy={"enabled": True, "allow": ["web_search"]},
        reason="llm:test",
        confidence=0.7,
        planner_mode="llm",
    )

    with patch(
        "mika_chat_core.planning.llm_planner.plan_with_llm",
        AsyncMock(return_value=llm_plan),
    ):
        plan = await build_request_plan_async(
            plugin_cfg=cfg,
            enable_tools=True,
            is_proactive=False,
            message="hi",
            image_urls_count=0,
            system_injection=None,
        )

    assert plan.planner_mode == "llm"
    assert plan.reply_mode == "tool_loop"
    assert plan.tool_policy.get("enabled") is True
    # gated by config: retrieval cannot be enabled if feature is off
    assert plan.use_memory_retrieval is False


@pytest.mark.asyncio
async def test_llm_planner_failure_falls_back_to_heuristic(valid_api_key: str):
    from mika_chat_core.config import Config
    from mika_chat_core.planning.planner import build_request_plan_async

    cfg = Config(
        llm_api_key=valid_api_key,
        mika_master_id=123456789,
        mika_planner_mode="llm",
        mika_planner_enabled=True,
    )

    with patch(
        "mika_chat_core.planning.llm_planner.plan_with_llm",
        AsyncMock(return_value=None),
    ):
        plan = await build_request_plan_async(
            plugin_cfg=cfg,
            enable_tools=True,
            is_proactive=False,
            message="hi",
            image_urls_count=0,
            system_injection=None,
        )

    assert plan.planner_mode == "heuristic"
    assert plan.reason.startswith("heuristic:")

