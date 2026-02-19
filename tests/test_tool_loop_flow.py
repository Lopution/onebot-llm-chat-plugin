from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from mika_chat_core.mika_api_layers.tools.tool_loop_flow import handle_tool_calls_flow


class _DummyLog:
    def debug(self, *_args, **_kwargs):
        return None

    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def success(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None


class _DummyMetrics:
    def __init__(self) -> None:
        self.tool_calls_total = 0
        self.tool_blocked_total = 0


async def _noop_hook(*_args, **_kwargs):
    return None


def _build_plugin_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        mika_tool_max_rounds=5,
        mika_tool_timeout_seconds=5.0,
        mika_tool_force_final_on_max_rounds=True,
        mika_react_enabled=False,
        mika_temperature=0.8,
        mika_tool_result_max_chars=500,
        mika_search_allow_tool_refine=True,
        mika_search_tool_refine_max_rounds=1,
    )


@pytest.mark.asyncio
async def test_tool_loop_empty_allowlist_allows_registered_tool():
    metrics = _DummyMetrics()
    executed: list[str] = []

    async def _handler(args: dict, group_id: str | None) -> str:
        executed.append(f"{group_id}:{args.get('x', '')}")
        return "tool-ok"

    with patch(
        "mika_chat_core.mika_api_layers.transport.facade.send_api_request",
        new=AsyncMock(return_value=({"role": "assistant", "content": "final"}, None, None)),
    ):
        result = await handle_tool_calls_flow(
            messages=[{"role": "user", "content": "hi"}],
            assistant_message={"role": "assistant", "content": ""},
            tool_calls=[
                {
                    "id": "call-1",
                    "function": {"name": "fetch_history_images", "arguments": '{"x": "1"}'},
                }
            ],
            api_key="k",
            group_id="g1",
            request_id="r1",
            tool_handlers={"fetch_history_images": _handler},
            model="m",
            base_url="https://example.com/v1",
            http_client=object(),
            tools=None,
            search_state=None,
            return_trace=True,
            plugin_cfg=_build_plugin_cfg(),
            log_obj=_DummyLog(),
            metrics_obj=metrics,
            emit_agent_hook_fn=_noop_hook,
            build_effective_allowlist_fn=lambda *_args, **_kwargs: set(),
            is_duplicate_search_query_fn=lambda *_args, **_kwargs: False,
        )

    assert result["reply"] == "final"
    assert executed == ["g1:1"]
    assert metrics.tool_blocked_total == 0
    tool_messages = [msg for msg in result["trace_messages"] if msg.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["content"] == "tool-ok"


@pytest.mark.asyncio
async def test_tool_loop_accepts_provider_prefixed_tool_name_alias():
    metrics = _DummyMetrics()
    executed: list[str] = []

    async def _handler(_args: dict, _group_id: str | None) -> str:
        executed.append("ok")
        return "alias-ok"

    with patch(
        "mika_chat_core.mika_api_layers.transport.facade.send_api_request",
        new=AsyncMock(return_value=({"role": "assistant", "content": "final"}, None, None)),
    ):
        result = await handle_tool_calls_flow(
            messages=[{"role": "user", "content": "hi"}],
            assistant_message={"role": "assistant", "content": ""},
            tool_calls=[
                {
                    "id": "call-2",
                    "function": {"name": "google:fetch_history_images", "arguments": "{}"},
                }
            ],
            api_key="k",
            group_id="g2",
            request_id="r2",
            tool_handlers={"fetch_history_images": _handler},
            model="m",
            base_url="https://example.com/v1",
            http_client=object(),
            tools=None,
            search_state=None,
            return_trace=True,
            plugin_cfg=_build_plugin_cfg(),
            log_obj=_DummyLog(),
            metrics_obj=metrics,
            emit_agent_hook_fn=_noop_hook,
            build_effective_allowlist_fn=lambda *_args, **_kwargs: {"fetch_history_images"},
            is_duplicate_search_query_fn=lambda *_args, **_kwargs: False,
        )

    assert result["reply"] == "final"
    assert executed == ["ok"]
    assert metrics.tool_blocked_total == 0
    tool_messages = [msg for msg in result["trace_messages"] if msg.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["name"] == "google:fetch_history_images"
    assert tool_messages[0]["content"] == "alias-ok"
