import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_tool_call_flow_triggers_handler():
    from mika_chat_core.gemini_api import GeminiClient

    with patch("mika_chat_core.gemini_api.HAS_SQLITE_STORE", False):
        client = GeminiClient(api_key="test-key")

        tool_calls = [
            {
                "id": "tool-1",
                "type": "function",
                "function": {"name": "web_search", "arguments": "{\"query\": \"test\"}"},
            }
        ]
        assistant_message = {"role": "assistant", "content": "", "tool_calls": tool_calls}

    with patch.object(client, "_pre_search", AsyncMock(return_value="")):
        with patch.object(
            client,
            "_build_messages",
            AsyncMock(return_value=([{"role": "user", "content": "hi"}], "hi", "hi", {})),
        ):
            with patch.object(
                client,
                "_send_api_request",
                AsyncMock(return_value=(assistant_message, tool_calls, "test-key")),
            ):
                with patch.object(
                    client,
                    "_handle_tool_calls",
                    AsyncMock(return_value="工具调用后的回复"),
                ) as mocked_handle:
                    reply = await client.chat("hi", user_id="user1", enable_tools=True)

        assert reply == "工具调用后的回复"
        mocked_handle.assert_called_once()


@pytest.mark.asyncio
async def test_chat_empty_reply_degradation_reuses_first_search_result():
    """空回复触发上下文降级时，应复用首轮搜索结果，避免重复触发分类/搜索。"""
    from mika_chat_core.gemini_api import GeminiClient

    with patch("mika_chat_core.gemini_api.HAS_SQLITE_STORE", False):
        client = GeminiClient(api_key="test-key")

    observed = []

    async def _fake_build_messages(
        message,
        user_id,
        group_id,
        image_urls,
        search_result,
        enable_tools=True,
        system_injection=None,
        context_level=0,
        history_override=None,
    ):
        observed.append((context_level, search_result))
        return (
            [{"role": "user", "content": "hi"}],
            "hi",
            "hi",
            {"messages": [{"role": "user", "content": "hi"}], "stream": False},
        )

    empty_assistant = {"role": "assistant", "content": ""}
    with patch(
        "mika_chat_core.gemini_api.plugin_config.gemini_empty_reply_context_degrade_enabled",
        True,
    ), patch.object(client, "_pre_search", AsyncMock(return_value="SEARCH_RESULT")) as mocked_pre_search, patch.object(
        client,
        "_build_messages",
        AsyncMock(side_effect=_fake_build_messages),
    ), patch.object(
        client,
        "_send_api_request",
        AsyncMock(return_value=(empty_assistant, None, "test-key")),
    ) as mocked_send, patch.object(
        client,
        "_resolve_reply",
        AsyncMock(side_effect=[("", []), ("", []), ("最终回复", [])]),
    ), patch.object(
        client,
        "_update_context",
        AsyncMock(),
    ), patch.object(
        client,
        "_log_context_diagnostics",
        AsyncMock(),
    ), patch("asyncio.sleep", new_callable=AsyncMock):
        reply = await client.chat("mika在吗", user_id="u1")

    assert reply == "最终回复"
    assert mocked_pre_search.await_count == 1
    assert mocked_send.await_count == 3
    assert observed == [
        (0, "SEARCH_RESULT"),
        (1, "SEARCH_RESULT"),
        (2, "SEARCH_RESULT"),
    ]


@pytest.mark.asyncio
async def test_chat_empty_reply_default_no_context_degrade():
    """默认配置下，空回复不触发业务级上下文降级，避免盲重跑整链路。"""
    from mika_chat_core.gemini_api import GeminiClient

    with patch("mika_chat_core.gemini_api.HAS_SQLITE_STORE", False):
        client = GeminiClient(api_key="test-key")

    observed_context_levels = []

    async def _fake_build_messages(
        message,
        user_id,
        group_id,
        image_urls,
        search_result,
        enable_tools=True,
        system_injection=None,
        context_level=0,
        history_override=None,
    ):
        observed_context_levels.append(context_level)
        return (
            [{"role": "user", "content": "hi"}],
            "hi",
            "hi",
            {"messages": [{"role": "user", "content": "hi"}], "stream": False},
        )

    empty_assistant = {
        "role": "assistant",
        "content": "",
        "_empty_reply_meta": {"kind": "provider_empty", "local_retries": 1},
    }
    with patch.object(client, "_pre_search", AsyncMock(return_value="SEARCH_RESULT")) as mocked_pre_search, patch.object(
        client,
        "_build_messages",
        AsyncMock(side_effect=_fake_build_messages),
    ), patch.object(
        client,
        "_send_api_request",
        AsyncMock(return_value=(empty_assistant, None, "test-key")),
    ) as mocked_send, patch.object(
        client,
        "_resolve_reply",
        AsyncMock(return_value=("", [])),
    ), patch.object(
        client,
        "_update_context",
        AsyncMock(),
    ), patch.object(
        client,
        "_log_context_diagnostics",
        AsyncMock(),
    ):
        reply = await client.chat("mika在吗", user_id="u1")

    assert "刚才走神了" in reply
    assert mocked_pre_search.await_count == 1
    assert mocked_send.await_count == 1
    assert observed_context_levels == [0]


@pytest.mark.asyncio
async def test_tool_call_unregistered_handler_returns_fallback():
    from mika_chat_core.gemini_api_tools import handle_tool_calls

    tool_calls = [
        {
            "id": "tool-1",
            "type": "function",
            "function": {"name": "web_search", "arguments": "{\"query\": \"test\"}"},
        }
    ]
    assistant_message = {"role": "assistant", "content": "", "tool_calls": tool_calls}

    mock_http = AsyncMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "最终回复"}, "finish_reason": "stop"}]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http.post = AsyncMock(return_value=mock_response)

    reply = await handle_tool_calls(
        messages=[{"role": "user", "content": "hi"}],
        assistant_message=assistant_message,
        tool_calls=tool_calls,
        api_key="test-key",
        group_id=None,
        request_id="req1",
        tool_handlers={},
        model="gemini-test",
        base_url="https://api.example.com",
        http_client=mock_http,
    )

    assert reply == "最终回复"


@pytest.mark.asyncio
async def test_tool_call_rejected_by_allowlist():
    from mika_chat_core.gemini_api_tools import handle_tool_calls

    tool_calls = [
        {
            "id": "tool-1",
            "type": "function",
            "function": {"name": "web_search", "arguments": "{\"query\": \"test\"}"},
        }
    ]
    assistant_message = {"role": "assistant", "content": "", "tool_calls": tool_calls}

    mock_http = AsyncMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "最终回复"}, "finish_reason": "stop"}]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http.post = AsyncMock(return_value=mock_response)

    with patch("mika_chat_core.gemini_api_tools.plugin_config.gemini_tool_allowlist", ["search_group_history"]):
        reply = await handle_tool_calls(
            messages=[{"role": "user", "content": "hi"}],
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            api_key="test-key",
            group_id=None,
            request_id="req1",
            tool_handlers={},
            model="gemini-test",
            base_url="https://api.example.com",
            http_client=mock_http,
        )

    assert reply == "最终回复"


@pytest.mark.asyncio
async def test_tool_call_loop_multiple_rounds_executes_handlers():
    """模型连续返回 tool_calls 时，应进行多轮 tool loop，直到拿到最终 content。"""
    from mika_chat_core.gemini_api_tools import handle_tool_calls

    tool_calls_round1 = [
        {
            "id": "tool-1",
            "type": "function",
            "function": {"name": "web_search", "arguments": "{\"query\": \"a\"}"},
        }
    ]
    assistant_message = {"role": "assistant", "content": "", "tool_calls": tool_calls_round1}

    # 1st follow-up: still asks for tool
    tool_calls_round2 = [
        {
            "id": "tool-2",
            "type": "function",
            "function": {"name": "web_search", "arguments": "{\"query\": \"b\"}"},
        }
    ]
    r1 = MagicMock()
    r1.raise_for_status = MagicMock()
    r1.json.return_value = {
        "choices": [
            {"message": {"content": "", "tool_calls": tool_calls_round2}, "finish_reason": "tool_calls"}
        ]
    }

    # 2nd follow-up: final content
    r2 = MagicMock()
    r2.raise_for_status = MagicMock()
    r2.json.return_value = {"choices": [{"message": {"content": "DONE"}, "finish_reason": "stop"}]}

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(side_effect=[r1, r2])

    tool_handler = AsyncMock(side_effect=["R1", "R2"])

    tools_schema = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "test",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]

    with patch("mika_chat_core.gemini_api_tools.plugin_config.gemini_tool_allowlist", ["web_search"]), patch(
        "mika_chat_core.gemini_api_tools.plugin_config.gemini_tool_max_rounds",
        5,
    ):
        reply = await handle_tool_calls(
            messages=[{"role": "user", "content": "hi"}],
            assistant_message=assistant_message,
            tool_calls=tool_calls_round1,
            api_key="test-key",
            group_id=None,
            request_id="req-loop",
            tool_handlers={"web_search": tool_handler},
            model="gemini-test",
            base_url="https://api.example.com",
            http_client=mock_http,
            tools=tools_schema,
        )

    assert reply == "DONE"
    assert tool_handler.await_count == 2
    assert mock_http.post.await_count == 2

    # 每轮请求都应继续携带 tools（除非达到上限强制最终）
    first_body = mock_http.post.call_args_list[0].kwargs["json"]
    second_body = mock_http.post.call_args_list[1].kwargs["json"]
    assert first_body.get("tools") == tools_schema
    assert second_body.get("tools") == tools_schema


@pytest.mark.asyncio
async def test_tool_call_loop_max_rounds_forces_final_response():
    """达到 max_rounds 后，应拔掉 tools 并强制模型给出最终答复。"""
    from mika_chat_core.gemini_api_tools import handle_tool_calls

    tool_calls_round1 = [
        {
            "id": "tool-1",
            "type": "function",
            "function": {"name": "web_search", "arguments": "{\"query\": \"a\"}"},
        }
    ]
    assistant_message = {"role": "assistant", "content": "", "tool_calls": tool_calls_round1}

    # follow-up: still asks for tool, but max_rounds=1 should stop here
    tool_calls_round2 = [
        {
            "id": "tool-2",
            "type": "function",
            "function": {"name": "web_search", "arguments": "{\"query\": \"b\"}"},
        }
    ]
    r1 = MagicMock()
    r1.raise_for_status = MagicMock()
    r1.json.return_value = {
        "choices": [
            {"message": {"content": "", "tool_calls": tool_calls_round2}, "finish_reason": "tool_calls"}
        ]
    }

    # final forced response
    r2 = MagicMock()
    r2.raise_for_status = MagicMock()
    r2.json.return_value = {"choices": [{"message": {"content": "FINAL"}, "finish_reason": "stop"}]}

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(side_effect=[r1, r2])

    tool_handler = AsyncMock(return_value="R1")

    tools_schema = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "test",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]

    with patch("mika_chat_core.gemini_api_tools.plugin_config.gemini_tool_allowlist", ["web_search"]), patch(
        "mika_chat_core.gemini_api_tools.plugin_config.gemini_tool_max_rounds",
        1,
    ), patch(
        "mika_chat_core.gemini_api_tools.plugin_config.gemini_tool_force_final_on_max_rounds",
        True,
    ):
        reply = await handle_tool_calls(
            messages=[{"role": "user", "content": "hi"}],
            assistant_message=assistant_message,
            tool_calls=tool_calls_round1,
            api_key="test-key",
            group_id=None,
            request_id="req-max",
            tool_handlers={"web_search": tool_handler},
            model="gemini-test",
            base_url="https://api.example.com",
            http_client=mock_http,
            tools=tools_schema,
        )

    assert reply == "FINAL"
    assert tool_handler.await_count == 1
    assert mock_http.post.await_count == 2

    first_body = mock_http.post.call_args_list[0].kwargs["json"]
    second_body = mock_http.post.call_args_list[1].kwargs["json"]
    assert first_body.get("tools") == tools_schema
    assert "tools" not in second_body  # 强制最终答复时不再暴露 tools
    assert any(
        "工具调用次数已达到上限" in (m.get("content") or "")
        for m in (second_body.get("messages") or [])
        if m.get("role") == "user"
    )


@pytest.mark.asyncio
async def test_search_injection_in_build_messages():
    from mika_chat_core.gemini_api_messages import pre_search, build_messages

    async def fake_get_context_async(user_id, group_id=None):
        return []

    tool_handlers = {"web_search": AsyncMock()}

    with patch(
        "mika_chat_core.gemini_api_messages.plugin_config.gemini_search_llm_gate_enabled",
        False,
    ), patch("mika_chat_core.utils.search_engine.should_search", return_value=True), patch(
        "mika_chat_core.utils.search_engine.serper_search", AsyncMock(return_value="SEARCH_RESULT")
    ):
        search_result = await pre_search(
            "今天有什么新闻",
            enable_tools=True,
            request_id="req1",
            tool_handlers=tool_handlers,
            enable_smart_search=False,
            get_context_async=fake_get_context_async,
            get_api_key=lambda: "key",
            base_url="https://api.example.com",
            user_id="u1",
            group_id="g1",
        )

    result = await build_messages(
        "今天有什么新闻",
        user_id="u1",
        group_id="g1",
        image_urls=None,
        search_result=search_result,
        model="gemini-test",
        system_prompt="你是助手",
        available_tools=[],
        system_injection=None,
        context_level=0,
        get_context_async=fake_get_context_async,
        use_persistent=False,
        context_store=None,
        has_image_processor=False,
        get_image_processor=None,
        has_user_profile=False,
        get_user_profile_store=None,
    )

    # 搜索结果不应以高权限 system 注入（降低 prompt injection 风险）
    injected_system = [
        msg
        for msg in result.messages
        if msg.get("role") == "system" and "实时事实注入" in msg.get("content", "")
    ]
    assert not injected_system

    # 搜索结果应以低权限消息注入，并带有“不可信/忽略指令”等免责声明与强分隔
    injected = [
        msg
        for msg in result.messages
        if msg.get("role") == "user" and "External Search Results" in msg.get("content", "")
    ]
    assert injected
    assert "SEARCH_RESULT" in injected[0].get("content", "")


@pytest.mark.asyncio
async def test_build_messages_history_override_bypasses_get_context_async():
    """history_override 非 None 时，不应调用 get_context_async（用于主动发言清空上下文场景）。"""
    from mika_chat_core.gemini_api_messages import build_messages

    get_context_async = AsyncMock(return_value=[{"role": "assistant", "content": "SHOULD_NOT_BE_USED"}])

    result = await build_messages(
        "hi",
        user_id="u1",
        group_id="g1",
        image_urls=None,
        search_result="",
        model="gemini-test",
        system_prompt="你是助手",
        available_tools=[],
        system_injection=None,
        context_level=0,
        history_override=[],
        get_context_async=get_context_async,
        use_persistent=False,
        context_store=None,
        has_image_processor=False,
        get_image_processor=None,
        has_user_profile=False,
        get_user_profile_store=None,
    )

    assert get_context_async.await_count == 0
    assert all("SHOULD_NOT_BE_USED" not in str(m.get("content")) for m in (result.messages or []))


@pytest.mark.asyncio
async def test_pre_search_llm_gate_needs_search_triggers_serper():
    from mika_chat_core.gemini_api_messages import pre_search

    async def fake_get_context_async(user_id, group_id=None):
        return []

    tool_handlers = {"web_search": AsyncMock()}

    with patch(
        "mika_chat_core.gemini_api_messages.plugin_config.gemini_search_llm_gate_enabled",
        True,
    ), patch(
        "mika_chat_core.gemini_api_messages.plugin_config.gemini_search_llm_gate_fallback_mode",
        "strong_timeliness",
    ), patch(
        "mika_chat_core.utils.search_engine.classify_topic_for_search",
        AsyncMock(return_value=(True, "AI模型", "@mika [小明(123456)]: 请帮我查一下 Kimi K2 发布 谢谢")),
    ), patch(
        "mika_chat_core.utils.search_engine.serper_search",
        AsyncMock(return_value="SEARCH_RESULT"),
    ) as mocked_serper:
        search_result = await pre_search(
            "kimi k2好像已经是老的模型了吧？",
            enable_tools=True,
            request_id="req1",
            tool_handlers=tool_handlers,
            enable_smart_search=True,
            get_context_async=fake_get_context_async,
            get_api_key=lambda: "key",
            base_url="https://api.example.com",
            user_id="u1",
            group_id="g1",
        )

    assert search_result == "SEARCH_RESULT"
    mocked_serper.assert_called_once()

    # prompt 清洗：最终送入 serper_search 的 query 不应包含噪声
    called_query = mocked_serper.call_args.args[0]
    lowered = called_query.lower()
    assert "mika" not in lowered
    assert "@" not in called_query
    assert "(123456)" not in called_query
    assert "谢谢" not in called_query


@pytest.mark.asyncio
async def test_send_api_request_content_empty_reasoning_triggers_completion_request():
    """主对话 content 为空但 reasoning_content 存在时，应触发补全请求且最终返回非空 content（仅一次）。"""
    from mika_chat_core.gemini_api_transport import send_api_request

    # mock http client: 两次响应
    mock_http = AsyncMock()

    # 1st: content empty but reasoning_content present
    r1 = MagicMock()
    r1.status_code = 200
    r1.json.return_value = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "", "reasoning_content": "internal reasoning"},
                "finish_reason": "stop",
            }
        ]
    }
    r1.raise_for_status = MagicMock()

    # 2nd: completion returns actual content
    r2 = MagicMock()
    r2.status_code = 200
    r2.json.return_value = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "最终回答"},
                "finish_reason": "stop",
            }
        ]
    }
    r2.raise_for_status = MagicMock()

    mock_http.post = AsyncMock(side_effect=[r1, r2])

    assistant_message, tool_calls, api_key = await send_api_request(
        http_client=mock_http,
        request_body={
            "model": "gemini-test",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
        request_id="req1",
        retry_count=0,
        api_key="test-key",
        base_url="https://api.example.com",
        model="gemini-test",
    )

    assert tool_calls is None
    assert api_key == "test-key"
    assert assistant_message.get("content") == "最终回答"

    # 确保只补全一次：共调用 2 次 post
    assert mock_http.post.call_count == 2


@pytest.mark.asyncio
async def test_send_api_request_content_empty_without_reasoning_local_retry_success():
    """主对话 content 为空且无 reasoning 时，应在 transport 层本地重试一次并直接收敛。"""
    from mika_chat_core.gemini_api_transport import send_api_request

    mock_http = AsyncMock()

    # 1st: empty content, no reasoning
    r1 = MagicMock()
    r1.status_code = 200
    r1.json.return_value = {
        "id": "resp-empty",
        "choices": [
            {
                "message": {"role": "assistant", "content": ""},
                "finish_reason": "stop",
            }
        ],
    }
    r1.raise_for_status = MagicMock()

    # 2nd: local retry succeeds
    r2 = MagicMock()
    r2.status_code = 200
    r2.json.return_value = {
        "id": "resp-ok",
        "choices": [
            {
                "message": {"role": "assistant", "content": "补偿回答"},
                "finish_reason": "stop",
            }
        ],
    }
    r2.raise_for_status = MagicMock()

    mock_http.post = AsyncMock(side_effect=[r1, r2])

    with patch("asyncio.sleep", new_callable=AsyncMock):
        assistant_message, tool_calls, api_key = await send_api_request(
            http_client=mock_http,
            request_body={
                "model": "gemini-test",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
            request_id="req-empty-local-retry",
            retry_count=0,
            api_key="test-key",
            base_url="https://api.example.com",
            model="gemini-test",
        )

    assert tool_calls is None
    assert api_key == "test-key"
    assert assistant_message.get("content") == "补偿回答"
    assert mock_http.post.call_count == 2


@pytest.mark.asyncio
async def test_send_api_request_timeout_local_retry_success():
    """主请求超时时，应在传输层本地重试并收敛。"""
    from mika_chat_core.gemini_api_transport import send_api_request

    mock_http = AsyncMock()
    r_ok = MagicMock()
    r_ok.status_code = 200
    r_ok.json.return_value = {
        "id": "resp-timeout-retry-ok",
        "choices": [
            {
                "message": {"role": "assistant", "content": "timeout retry ok"},
                "finish_reason": "stop",
            }
        ],
    }
    r_ok.raise_for_status = MagicMock()

    mock_http.post = AsyncMock(side_effect=[httpx.TimeoutException("timeout"), r_ok])

    with patch("asyncio.sleep", new_callable=AsyncMock), patch(
        "mika_chat_core.gemini_api_transport.plugin_config.gemini_transport_timeout_retries",
        1,
    ), patch(
        "mika_chat_core.gemini_api_transport.plugin_config.gemini_transport_timeout_retry_delay_seconds",
        0.01,
    ):
        assistant_message, tool_calls, api_key = await send_api_request(
            http_client=mock_http,
            request_body={
                "model": "gemini-test",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
            request_id="req-timeout-local-retry",
            retry_count=0,
            api_key="test-key",
            base_url="https://api.example.com",
            model="gemini-test",
        )

    assert tool_calls is None
    assert api_key == "test-key"
    assert assistant_message.get("content") == "timeout retry ok"
    assert mock_http.post.call_count == 2


@pytest.mark.asyncio
async def test_send_api_request_timeout_no_local_retry_raises():
    """关闭超时重试后，TimeoutException 应直接抛出给上层。"""
    from mika_chat_core.gemini_api_transport import send_api_request

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch(
        "mika_chat_core.gemini_api_transport.plugin_config.gemini_transport_timeout_retries",
        0,
    ):
        with pytest.raises(httpx.TimeoutException):
            await send_api_request(
                http_client=mock_http,
                request_body={
                    "model": "gemini-test",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                },
                request_id="req-timeout-no-retry",
                retry_count=0,
                api_key="test-key",
                base_url="https://api.example.com",
                model="gemini-test",
            )


@pytest.mark.asyncio
async def test_pre_search_llm_gate_no_search_skips_serper():
    from mika_chat_core.gemini_api_messages import pre_search

    async def fake_get_context_async(user_id, group_id=None):
        return []

    tool_handlers = {"web_search": AsyncMock()}

    with patch(
        "mika_chat_core.gemini_api_messages.plugin_config.gemini_search_llm_gate_enabled",
        True,
    ), patch(
        "mika_chat_core.utils.search_engine.classify_topic_for_search",
        AsyncMock(return_value=(False, "闲聊", "")),
    ), patch(
        "mika_chat_core.utils.search_engine.serper_search",
        AsyncMock(return_value="SEARCH_RESULT"),
    ) as mocked_serper:
        search_result = await pre_search(
            "我今天好累",
            enable_tools=True,
            request_id="req1",
            tool_handlers=tool_handlers,
            enable_smart_search=True,
            get_context_async=fake_get_context_async,
            get_api_key=lambda: "key",
            base_url="https://api.example.com",
            user_id="u1",
            group_id="g1",
        )

    assert search_result == ""
    mocked_serper.assert_not_called()


@pytest.mark.asyncio
async def test_pre_search_llm_gate_failure_strong_timeliness_fallback():
    from mika_chat_core.gemini_api_messages import pre_search

    async def fake_get_context_async(user_id, group_id=None):
        return []

    tool_handlers = {"web_search": AsyncMock()}

    # classify 返回 (False, 未知, "") 视为失败，且消息命中强时效词（如“比赛结果”）应回退外搜
    with patch(
        "mika_chat_core.gemini_api_messages.plugin_config.gemini_search_llm_gate_enabled",
        True,
    ), patch(
        "mika_chat_core.gemini_api_messages.plugin_config.gemini_search_llm_gate_fallback_mode",
        "strong_timeliness",
    ), patch(
        "mika_chat_core.utils.search_engine.classify_topic_for_search",
        AsyncMock(return_value=(False, "未知", "")),
    ), patch(
        "mika_chat_core.utils.search_engine.serper_search",
        AsyncMock(return_value="SEARCH_RESULT"),
    ) as mocked_serper:
        search_result = await pre_search(
            "比赛结果出来了吗",
            enable_tools=True,
            request_id="req1",
            tool_handlers=tool_handlers,
            enable_smart_search=True,
            get_context_async=fake_get_context_async,
            get_api_key=lambda: "key",
            base_url="https://api.example.com",
            user_id="u1",
            group_id="g1",
        )

    assert search_result == "SEARCH_RESULT"
    mocked_serper.assert_called_once()


@pytest.mark.asyncio
async def test_search_injection_empty_result_not_injected():
    from mika_chat_core.gemini_api_messages import pre_search, build_messages

    async def fake_get_context_async(user_id, group_id=None):
        return []

    tool_handlers = {"web_search": AsyncMock()}

    with patch(
        "mika_chat_core.gemini_api_messages.plugin_config.gemini_search_llm_gate_enabled",
        False,
    ), patch("mika_chat_core.utils.search_engine.should_search", return_value=True), patch(
        "mika_chat_core.utils.search_engine.serper_search", AsyncMock(return_value="")
    ):
        search_result = await pre_search(
            "今天有什么新闻",
            enable_tools=True,
            request_id="req1",
            tool_handlers=tool_handlers,
            enable_smart_search=False,
            get_context_async=fake_get_context_async,
            get_api_key=lambda: "key",
            base_url="https://api.example.com",
            user_id="u1",
            group_id="g1",
        )

    result = await build_messages(
        "今天有什么新闻",
        user_id="u1",
        group_id="g1",
        image_urls=None,
        search_result=search_result,
        model="gemini-test",
        system_prompt="你是助手",
        available_tools=[],
        system_injection=None,
        context_level=0,
        get_context_async=fake_get_context_async,
        use_persistent=False,
        context_store=None,
        has_image_processor=False,
        get_image_processor=None,
        has_user_profile=False,
        get_user_profile_store=None,
    )

    injected = [msg for msg in result.messages if msg.get("role") == "system" and "实时事实注入" in msg.get("content", "")]
    assert not injected


@pytest.mark.asyncio
async def test_image_processing_in_build_messages():
    from mika_chat_core.gemini_api_messages import build_messages

    async def fake_get_context_async(user_id, group_id=None):
        return []

    mock_processor = AsyncMock()
    mock_processor.process_images = AsyncMock(
        return_value=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}]
    )

    result = await build_messages(
        "看图",
        user_id="u1",
        group_id=None,
        image_urls=["https://example.com/a.png"],
        search_result="",
        model="gemini-test",
        system_prompt="你是助手",
        available_tools=[],
        system_injection=None,
        context_level=0,
        get_context_async=fake_get_context_async,
        use_persistent=False,
        context_store=None,
        has_image_processor=True,
        get_image_processor=lambda *_args, **_kwargs: mock_processor,
        has_user_profile=False,
        get_user_profile_store=None,
    )

    user_message = result.messages[-1]
    assert user_message["role"] == "user"
    assert any(item.get("type") == "image_url" for item in user_message["content"])


@pytest.mark.asyncio
async def test_image_processing_fallback_to_url_on_error():
    from mika_chat_core.gemini_api_messages import build_messages

    async def fake_get_context_async(user_id, group_id=None):
        return []

    mock_processor = AsyncMock()
    mock_processor.process_images = AsyncMock(side_effect=Exception("boom"))

    result = await build_messages(
        "看图",
        user_id="u1",
        group_id=None,
        image_urls=["https://example.com/a.png"],
        search_result="",
        model="gemini-test",
        system_prompt="你是助手",
        available_tools=[],
        system_injection=None,
        context_level=0,
        get_context_async=fake_get_context_async,
        use_persistent=False,
        context_store=None,
        has_image_processor=True,
        get_image_processor=lambda *_args, **_kwargs: mock_processor,
        has_user_profile=False,
        get_user_profile_store=None,
    )

    user_message = result.messages[-1]
    assert user_message["role"] == "user"
    assert any(
        item.get("type") == "image_url" and item.get("image_url", {}).get("url") == "https://example.com/a.png"
        for item in user_message["content"]
    )


@pytest.mark.asyncio
async def test_build_messages_strips_tool_history_when_tools_disabled():
    from mika_chat_core.gemini_api_messages import build_messages

    async def fake_get_context_async(user_id, group_id=None):
        return [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "content": "tool-result", "tool_call_id": "c1"},
            {"role": "assistant", "content": "最终答案"},
        ]

    result = await build_messages(
        "继续",
        user_id="u1",
        group_id="g1",
        image_urls=None,
        search_result="",
        model="gemini-test",
        system_prompt="你是助手",
        available_tools=[],
        system_injection=None,
        context_level=0,
        get_context_async=fake_get_context_async,
        use_persistent=False,
        context_store=None,
        has_image_processor=False,
        get_image_processor=None,
        has_user_profile=False,
        get_user_profile_store=None,
        enable_tools=False,
    )

    roles = [msg.get("role") for msg in result.messages]
    assert "tool" not in roles
    assert any(msg.get("role") == "assistant" and msg.get("content") == "最终答案" for msg in result.messages)


@pytest.mark.asyncio
async def test_proactive_handler_triggers_group_reply():
    from mika_chat_core import matchers

    mock_event = MagicMock()
    mock_event.group_id = 1001
    mock_event.user_id = 2002
    mock_event.message_id = 3003
    mock_event.get_plaintext.return_value = "聊点什么"

    mock_sender = MagicMock()
    mock_sender.card = "群友"
    mock_sender.nickname = "User"
    mock_event.sender = mock_sender

    mock_bot = AsyncMock()

    mock_context_store = AsyncMock()
    mock_context_store.get_context = AsyncMock(return_value=[])

    mock_client = AsyncMock()
    mock_client.context_store = mock_context_store
    mock_client.judge_proactive_intent = AsyncMock(return_value={"should_reply": True})

    with patch(
        "mika_chat_core.matchers.parse_message_with_mentions",
        AsyncMock(return_value=("", [])),
    ), patch("mika_chat_core.deps.get_gemini_client_dep", return_value=mock_client), patch(
        "mika_chat_core.matchers.handle_group", AsyncMock()
    ) as mocked_handle_group:
        await matchers._handle_proactive(mock_bot, mock_event)

    mocked_handle_group.assert_called_once()
    call_kwargs = mocked_handle_group.call_args.kwargs
    assert call_kwargs.get("is_proactive") is True
    # 新行为：不再注入 proactive_reason 系统提示，只标记 is_proactive
    assert "proactive_reason" not in call_kwargs


@pytest.mark.asyncio
async def test_proactive_handler_skips_when_judge_rejects():
    from mika_chat_core import matchers

    mock_event = MagicMock()
    mock_event.group_id = 1001
    mock_event.user_id = 2002
    mock_event.message_id = 3003
    mock_event.get_plaintext.return_value = "聊点什么"

    mock_sender = MagicMock()
    mock_sender.card = "群友"
    mock_sender.nickname = "User"
    mock_event.sender = mock_sender

    mock_bot = AsyncMock()

    mock_context_store = AsyncMock()
    mock_context_store.get_context = AsyncMock(return_value=[])

    mock_client = AsyncMock()
    mock_client.context_store = mock_context_store
    mock_client.judge_proactive_intent = AsyncMock(return_value={"should_reply": False})

    with patch("mika_chat_core.deps.get_gemini_client_dep", return_value=mock_client), patch(
        "mika_chat_core.matchers.handle_group", AsyncMock()
    ) as mocked_handle_group:
        await matchers._handle_proactive(mock_bot, mock_event)

    mocked_handle_group.assert_not_called()


@pytest.mark.asyncio
async def test_proactive_handler_prefers_parsed_text_for_judge_context():
    from mika_chat_core import matchers

    mock_event = MagicMock()
    mock_event.group_id = 1001
    mock_event.user_id = 2002
    mock_event.message_id = 3003
    mock_event.get_plaintext.return_value = "原始文本"

    mock_sender = MagicMock()
    mock_sender.card = "群友"
    mock_sender.nickname = "User"
    mock_event.sender = mock_sender

    mock_bot = AsyncMock()

    mock_context_store = AsyncMock()
    mock_context_store.get_context = AsyncMock(return_value=[])

    mock_client = AsyncMock()
    mock_client.context_store = mock_context_store
    mock_client.judge_proactive_intent = AsyncMock(return_value={"should_reply": False})

    parsed_text = "@星鱼 你现在是啥专业"
    with patch(
        "mika_chat_core.matchers.parse_message_with_mentions",
        AsyncMock(return_value=(parsed_text, [])),
    ), patch("mika_chat_core.deps.get_gemini_client_dep", return_value=mock_client), patch(
        "mika_chat_core.matchers.handle_group", AsyncMock()
    ):
        await matchers._handle_proactive(mock_bot, mock_event)

    judge_args, _ = mock_client.judge_proactive_intent.await_args
    temp_context = judge_args[0]
    assert temp_context[-1]["content"] == parsed_text


@pytest.mark.asyncio
async def test_proactive_handler_fallbacks_to_plaintext_when_parse_fails():
    from mika_chat_core import matchers

    mock_event = MagicMock()
    mock_event.group_id = 1001
    mock_event.user_id = 2002
    mock_event.message_id = 3003
    mock_event.get_plaintext.return_value = "回退文本"

    mock_sender = MagicMock()
    mock_sender.card = "群友"
    mock_sender.nickname = "User"
    mock_event.sender = mock_sender

    mock_bot = AsyncMock()

    mock_context_store = AsyncMock()
    mock_context_store.get_context = AsyncMock(return_value=[])

    mock_client = AsyncMock()
    mock_client.context_store = mock_context_store
    mock_client.judge_proactive_intent = AsyncMock(return_value={"should_reply": False})

    with patch(
        "mika_chat_core.matchers.parse_message_with_mentions",
        AsyncMock(side_effect=RuntimeError("boom")),
    ), patch("mika_chat_core.deps.get_gemini_client_dep", return_value=mock_client), patch(
        "mika_chat_core.matchers.handle_group", AsyncMock()
    ):
        await matchers._handle_proactive(mock_bot, mock_event)

    judge_args, _ = mock_client.judge_proactive_intent.await_args
    temp_context = judge_args[0]
    assert temp_context[-1]["content"] == "回退文本"


@pytest.mark.asyncio
async def test_proactive_handler_resets_cooldown_and_message_count_before_judge():
    from mika_chat_core import matchers
    import time

    mock_event = MagicMock()
    mock_event.group_id = 1001
    mock_event.user_id = 2002
    mock_event.message_id = 3003
    mock_event.get_plaintext.return_value = "测试文本"

    mock_sender = MagicMock()
    mock_sender.card = "群友"
    mock_sender.nickname = "User"
    mock_event.sender = mock_sender

    mock_bot = AsyncMock()

    mock_context_store = AsyncMock()
    mock_context_store.get_context = AsyncMock(return_value=[])

    mock_client = AsyncMock()
    mock_client.context_store = mock_context_store
    mock_client.judge_proactive_intent = AsyncMock(return_value={"should_reply": False})

    group_key = str(mock_event.group_id)
    old_cooldowns = dict(matchers._proactive_cooldowns)
    old_counts = dict(matchers._proactive_message_counts)
    try:
        matchers._proactive_cooldowns[group_key] = 0.0
        matchers._proactive_message_counts[group_key] = 9
        t0 = time.time()

        with patch(
            "mika_chat_core.matchers.parse_message_with_mentions",
            AsyncMock(return_value=("测试文本", [])),
        ), patch("mika_chat_core.deps.get_gemini_client_dep", return_value=mock_client), patch(
            "mika_chat_core.matchers.handle_group", AsyncMock()
        ):
            await matchers._handle_proactive(mock_bot, mock_event)

        assert matchers._proactive_message_counts[group_key] == 0
        assert matchers._proactive_cooldowns[group_key] >= t0
    finally:
        matchers._proactive_cooldowns.clear()
        matchers._proactive_cooldowns.update(old_cooldowns)
        matchers._proactive_message_counts.clear()
        matchers._proactive_message_counts.update(old_counts)


@pytest.mark.asyncio
async def test_check_proactive_respects_cooldown():
    from mika_chat_core import matchers

    event = MagicMock()
    event.to_me = False
    event.group_id = 123
    event.user_id = 456
    event.get_plaintext.return_value = "Mika"
    event.message = []

    matchers.plugin_config.gemini_group_whitelist = []
    matchers.plugin_config.gemini_proactive_keywords = ["Mika"]
    matchers.plugin_config.gemini_proactive_cooldown = 100
    matchers.plugin_config.gemini_proactive_cooldown_messages = 0
    matchers.plugin_config.gemini_proactive_rate = 1.0
    matchers.plugin_config.gemini_proactive_ignore_len = 0

    matchers._proactive_cooldowns[str(event.group_id)] = __import__("time").time()

    result = await matchers.check_proactive(event)
    assert result is False


@pytest.mark.asyncio
async def test_pre_search_llm_gate_enabled_does_not_call_should_search():
    """当 llm_gate_enabled=True 时，即使关键词命中也不调用 should_search()"""
    from mika_chat_core.gemini_api_messages import pre_search

    async def fake_get_context_async(user_id, group_id=None):
        return []

    tool_handlers = {"web_search": AsyncMock()}

    # should_search 不应被调用（即使消息包含关键词）
    with patch(
        "mika_chat_core.gemini_api_messages.plugin_config.gemini_search_llm_gate_enabled",
        True,
    ), patch(
        "mika_chat_core.gemini_api_messages.plugin_config.gemini_search_llm_gate_fallback_mode",
        "strong_timeliness",
    ), patch(
        "mika_chat_core.utils.search_engine.should_search",
        MagicMock(return_value=True),
    ) as mocked_should_search, patch(
        "mika_chat_core.utils.search_engine.classify_topic_for_search",
        AsyncMock(return_value=(False, "闲聊", "")),
    ), patch(
        "mika_chat_core.utils.search_engine.serper_search",
        AsyncMock(return_value="SEARCH_RESULT"),
    ) as mocked_serper:
        search_result = await pre_search(
            "今天天气怎么样",  # 包含"天气"关键词，should_search 会返回 True
            enable_tools=True,
            request_id="req1",
            tool_handlers=tool_handlers,
            enable_smart_search=True,
            get_context_async=fake_get_context_async,
            get_api_key=lambda: "key",
            base_url="https://api.example.com",
            user_id="u1",
            group_id="g1",
        )

    # LLM gate 判定无需搜索，不应调用 serper
    assert search_result == ""
    mocked_serper.assert_not_called()
    # 关键：should_search 不应被调用
    mocked_should_search.assert_not_called()


@pytest.mark.asyncio
async def test_pre_search_llm_gate_enabled_smart_search_disabled_skips_all():
    """当 llm_gate_enabled=True 但 enable_smart_search=False 时，直接跳过搜索，不走关键词路径"""
    from mika_chat_core.gemini_api_messages import pre_search

    async def fake_get_context_async(user_id, group_id=None):
        return []

    tool_handlers = {"web_search": AsyncMock()}

    with patch(
        "mika_chat_core.gemini_api_messages.plugin_config.gemini_search_llm_gate_enabled",
        True,
    ), patch(
        "mika_chat_core.utils.search_engine.should_search",
        MagicMock(return_value=True),
    ) as mocked_should_search, patch(
        "mika_chat_core.utils.search_engine.classify_topic_for_search",
        AsyncMock(return_value=(True, "天气", "今天天气")),
    ) as mocked_classify, patch(
        "mika_chat_core.utils.search_engine.serper_search",
        AsyncMock(return_value="SEARCH_RESULT"),
    ) as mocked_serper:
        search_result = await pre_search(
            "今天天气怎么样",
            enable_tools=True,
            request_id="req1",
            tool_handlers=tool_handlers,
            enable_smart_search=False,  # 关键：smart_search 关闭
            get_context_async=fake_get_context_async,
            get_api_key=lambda: "key",
            base_url="https://api.example.com",
            user_id="u1",
            group_id="g1",
        )

    # gate 开启但 smart_search 关闭，不应调用任何搜索相关函数
    assert search_result == ""
    mocked_should_search.assert_not_called()
    mocked_classify.assert_not_called()
    mocked_serper.assert_not_called()


@pytest.mark.asyncio
async def test_pre_search_llm_gate_disabled_still_uses_should_search():
    """当 llm_gate_enabled=False 时，仍然使用 should_search() 关键词路径"""
    from mika_chat_core.gemini_api_messages import pre_search

    async def fake_get_context_async(user_id, group_id=None):
        return []

    tool_handlers = {"web_search": AsyncMock()}

    with patch(
        "mika_chat_core.gemini_api_messages.plugin_config.gemini_search_llm_gate_enabled",
        False,
    ), patch(
        "mika_chat_core.utils.search_engine.should_search",
        MagicMock(return_value=True),
    ) as mocked_should_search, patch(
        "mika_chat_core.utils.search_engine.serper_search",
        AsyncMock(return_value="SEARCH_RESULT"),
    ) as mocked_serper:
        search_result = await pre_search(
            "今天天气怎么样",
            enable_tools=True,
            request_id="req1",
            tool_handlers=tool_handlers,
            enable_smart_search=False,  # smart_search 关闭
            get_context_async=fake_get_context_async,
            get_api_key=lambda: "key",
            base_url="https://api.example.com",
            user_id="u1",
            group_id="g1",
        )

    # gate 未开启，应该走关键词路径
    assert search_result == "SEARCH_RESULT"
    mocked_should_search.assert_called_once()
    mocked_serper.assert_called_once()
