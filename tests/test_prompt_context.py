"""prompt_context 与模板渲染测试。"""

from __future__ import annotations

import pytest

from mika_chat_core.utils.prompt_context import (
    get_prompt_context,
    reset_prompt_context,
    set_prompt_context,
    update_prompt_context,
)
from mika_chat_core.utils.prompt_loader import render_template


def test_prompt_context_set_update_reset():
    token = set_prompt_context({"master_name": "Sensei"})
    try:
        assert get_prompt_context()["master_name"] == "Sensei"
        merged = update_prompt_context({"time_block": "晚上"})
        assert merged["master_name"] == "Sensei"
        assert merged["time_block"] == "晚上"
    finally:
        reset_prompt_context(token)

    assert get_prompt_context() == {}


def test_render_template_replaces_known_keys_only():
    rendered = render_template(
        "你好，{master_name}。当前时段：{time_block}。保留未知：{unknown_key}",
        {
            "master_name": "老师",
            "time_block": "深夜",
        },
    )
    assert "老师" in rendered
    assert "深夜" in rendered
    assert "{unknown_key}" in rendered


def test_render_template_stringify_list_and_dict():
    rendered = render_template(
        "记忆:\n{memory_snippets}\n档案:\n{user_profile}",
        {
            "memory_snippets": ["- 喜欢红茶", "- 周末打羽毛球"],
            "user_profile": {"nickname": "小明", "city": "杭州"},
        },
    )
    assert "- 喜欢红茶" in rendered
    assert "nickname: 小明" in rendered
    assert "city: 杭州" in rendered

