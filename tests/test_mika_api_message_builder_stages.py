"""message_builder_stages 单测。"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


class _GuardResult:
    def __init__(self, *, text: str, detected: bool = False, action: str = "annotate", matches=None):
        self.text = text
        self.detected = detected
        self.action = action
        self.matches = list(matches or [])


def _identity_normalize(content):
    return content


@pytest.mark.asyncio
async def test_build_original_and_api_content_without_processor_keeps_urls():
    from mika_chat_core.mika_api_layers.builder.stages import build_original_and_api_content

    log = Mock()
    cfg = SimpleNamespace(mika_image_download_concurrency=2)
    original, api_content = await build_original_and_api_content(
        message="hello",
        normalized_image_urls=["https://example.com/a.png", "data:image/png;base64,abc"],
        has_image_processor=False,
        get_image_processor=lambda _c: None,
        plugin_cfg=cfg,
        log_obj=log,
    )
    assert isinstance(original, list)
    assert original[0] == {"type": "text", "text": "hello"}
    assert api_content[0] == {"type": "text", "text": "hello"}
    assert all(
        isinstance(item, dict)
        and item.get("type") == "image_url"
        and isinstance(item.get("mika_media"), dict)
        for item in original[1:]
    )
    assert {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}} in api_content
    assert {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}} in api_content


def test_guard_inputs_logs_when_injection_detected():
    from mika_chat_core.mika_api_layers.builder.stages import guard_inputs

    log = Mock()
    cfg = SimpleNamespace(
        mika_prompt_injection_guard_enabled=True,
        mika_prompt_injection_guard_action="annotate",
        mika_prompt_injection_guard_patterns=["忽略之前所有指令"],
    )

    def fake_guard(text, **_kwargs):
        if text == "user":
            return _GuardResult(text="[guarded-user]", detected=True, matches=["x"])
        return _GuardResult(text="[guarded-search]", detected=True, matches=["y", "z"])

    guarded_user, guarded_search = guard_inputs(
        message="user",
        search_result="search",
        plugin_cfg=cfg,
        log_obj=log,
        guard_untrusted_text_fn=fake_guard,
    )
    assert guarded_user == "[guarded-user]"
    assert guarded_search == "[guarded-search]"
    assert log.warning.call_count == 2


@pytest.mark.asyncio
async def test_build_enhanced_system_prompt_injects_profile_time_and_react():
    from mika_chat_core.mika_api_layers.builder.stages import build_enhanced_system_prompt

    log = Mock()
    cfg = SimpleNamespace(mika_react_enabled=True)

    class _ProfileStore:
        async def get_profile_summary(self, _user_id):
            return "喜欢数学"

    out = await build_enhanced_system_prompt(
        system_prompt="base",
        user_id="u1",
        has_user_profile=True,
        use_persistent=True,
        get_user_profile_store=lambda: _ProfileStore(),
        plugin_cfg=cfg,
        log_obj=log,
        current_time_display="2026-02-17 12:00",
        load_react_prompt_fn=lambda: {"react_system_suffix": "react-suffix"},
    )
    assert "[用户档案 - 请记住这些信息]" in out
    assert "Current Time: 2026-02-17 12:00" in out
    assert "react-suffix" in out


@pytest.mark.asyncio
async def test_append_history_messages_drops_tool_when_provider_not_support_tools():
    from mika_chat_core.mika_api_layers.builder.stages import append_history_messages

    log = Mock()
    now = time.time()
    history = [
        {"role": "tool", "content": "hidden"},
        {"role": "assistant", "content": "reply", "timestamp": now - 120},
    ]

    async def fake_get_context_async(_uid, _gid):
        return history

    def fake_sanitize(raw_msg, **_kwargs):
        return dict(raw_msg)

    messages, dropped_tools, dropped_images = await append_history_messages(
        messages=[{"role": "system", "content": "sys"}],
        user_id="u1",
        group_id="g1",
        history_override=None,
        get_context_async=fake_get_context_async,
        context_level=0,
        use_persistent=False,
        context_store=None,
        supports_images=True,
        supports_tools=False,
        normalize_content_fn=_identity_normalize,
        sanitize_history_message_for_request_fn=fake_sanitize,
        log_obj=log,
    )
    assert dropped_tools == 1
    assert dropped_images == 0
    assert len(messages) == 2
    assert messages[-1]["role"] == "assistant"
    assert str(messages[-1]["content"]).startswith("[几分钟前] ")


def test_filter_tools_for_request_respects_allowlist_and_presearch_refine():
    from mika_chat_core.mika_api_layers.builder.stages import filter_tools_for_request

    log = Mock()
    cfg = SimpleNamespace(
        mika_search_allow_tool_refine=False,
        mika_tool_allowlist=["web_search", "search_group_history"],
        mika_tool_allow_dynamic_registered=True,
    )
    available_tools = [
        {"type": "function", "function": {"name": "web_search"}},
        {"type": "function", "function": {"name": "search_group_history"}},
        {"type": "function", "function": {"name": "fetch_history_images"}},
    ]

    filtered, presearch_hit = filter_tools_for_request(
        available_tools=available_tools,
        search_result="已有结果",
        plugin_cfg=cfg,
        build_effective_allowlist_fn=lambda _alist, include_dynamic_sources: {"web_search", "search_group_history"}
        if include_dynamic_sources
        else {"web_search"},
        is_presearch_result_insufficient_fn=lambda _s: True,
        estimate_injected_result_count_fn=lambda _s: 3,
        log_obj=log,
    )
    assert presearch_hit is True
    # presearch 命中且不允许 refine 时，web_search 应被隐藏
    assert [t["function"]["name"] for t in filtered] == ["search_group_history"]
