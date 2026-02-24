"""API Key 轮换策略单测。"""

from __future__ import annotations

from unittest.mock import Mock, patch


def test_select_api_key_returns_primary_when_list_empty():
    from mika_chat_core.mika_api_layers.core.key_rotation import select_api_key

    log = Mock()
    selected, next_index = select_api_key(
        api_key="primary",
        api_key_list=[],
        key_index=0,
        key_cooldowns={},
        log_obj=log,
    )
    assert selected == "primary"
    assert next_index == 0


def test_select_api_key_skips_cooldown_and_clears_expired_entry():
    from mika_chat_core.mika_api_layers.core.key_rotation import select_api_key

    log = Mock()
    key_cooldowns = {"k1": 120.0, "k2": 80.0}
    with patch("mika_chat_core.mika_api_layers.core.key_rotation.time.monotonic", return_value=100.0):
        selected, next_index = select_api_key(
            api_key="unused",
            api_key_list=["k1", "k2"],
            key_index=0,
            key_cooldowns=key_cooldowns,
            log_obj=log,
        )
    assert selected == "k2"
    assert next_index == 0
    assert "k2" not in key_cooldowns
    log.debug.assert_any_call("API Key #1 仍在冷却中（剩余 20s），跳过")
    log.debug.assert_any_call("API Key #0 冷却期结束，恢复使用")


def test_select_api_key_uses_shortest_cooldown_when_all_blocked():
    from mika_chat_core.mika_api_layers.core.key_rotation import select_api_key

    log = Mock()
    key_cooldowns = {"k1": 300.0, "k2": 150.0, "k3": 200.0}
    with patch("mika_chat_core.mika_api_layers.core.key_rotation.time.monotonic", return_value=100.0):
        selected, next_index = select_api_key(
            api_key="unused",
            api_key_list=["k1", "k2", "k3"],
            key_index=1,
            key_cooldowns=key_cooldowns,
            log_obj=log,
        )
    assert selected == "k2"
    assert next_index == 1
    log.warning.assert_called_once_with("所有 API Key 都在冷却期，强制使用冷却时间最短的 Key")


def test_mark_key_rate_limited_uses_default_when_retry_after_non_positive():
    from mika_chat_core.mika_api_layers.core.key_rotation import mark_key_rate_limited

    log = Mock()
    key_cooldowns = {}
    with patch("mika_chat_core.mika_api_layers.core.key_rotation.time.monotonic", return_value=50.0):
        mark_key_rate_limited(
            key="k1",
            retry_after=0,
            default_cooldown=30,
            key_cooldowns=key_cooldowns,
            log_obj=log,
        )
    assert key_cooldowns["k1"] == 80.0
    log.warning.assert_called_once_with("API Key 被限流，进入冷却期 30s")
