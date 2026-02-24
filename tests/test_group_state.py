from __future__ import annotations

from mika_chat_core import group_state


def test_proactive_state_prunes_by_ttl(monkeypatch):
    group_state.get_proactive_cooldowns().clear()
    group_state.get_proactive_message_counts().clear()
    group_state._proactive_last_seen.clear()
    monkeypatch.setattr(group_state, "_proactive_next_prune_at", 0.0)

    group_state.get_proactive_cooldowns()["g1"] = 10.0
    group_state.get_proactive_message_counts()["g1"] = 3
    group_state._proactive_last_seen["g1"] = 10.0

    current = 10.0 + group_state.PROACTIVE_STATE_TTL_SECONDS + 1.0
    group_state.prune_proactive_state(now=current)

    assert "g1" not in group_state.get_proactive_cooldowns()
    assert "g1" not in group_state.get_proactive_message_counts()
    assert "g1" not in group_state._proactive_last_seen


def test_proactive_state_prunes_by_capacity(monkeypatch):
    group_state.get_proactive_cooldowns().clear()
    group_state.get_proactive_message_counts().clear()
    group_state._proactive_last_seen.clear()
    monkeypatch.setattr(group_state, "_proactive_next_prune_at", 0.0)

    monkeypatch.setattr(group_state, "PROACTIVE_STATE_MAX_GROUPS", 2)
    monkeypatch.setattr(group_state, "PROACTIVE_STATE_TTL_SECONDS", 10_000.0)

    group_state.touch_proactive_group("g1", now=1.0)
    group_state.get_proactive_cooldowns()["g1"] = 1.0
    group_state.get_proactive_message_counts()["g1"] = 1

    group_state.touch_proactive_group("g2", now=2.0)
    group_state.get_proactive_cooldowns()["g2"] = 2.0
    group_state.get_proactive_message_counts()["g2"] = 2

    group_state.touch_proactive_group("g3", now=3.0)
    group_state.get_proactive_cooldowns()["g3"] = 3.0
    group_state.get_proactive_message_counts()["g3"] = 3

    assert "g1" not in group_state._proactive_last_seen
    assert "g1" not in group_state.get_proactive_cooldowns()
    assert "g1" not in group_state.get_proactive_message_counts()
    assert set(group_state._proactive_last_seen.keys()) == {"g2", "g3"}


def test_touch_proactive_group_prunes_by_interval(monkeypatch):
    group_state.get_proactive_cooldowns().clear()
    group_state.get_proactive_message_counts().clear()
    group_state._proactive_last_seen.clear()

    monkeypatch.setattr(group_state, "PROACTIVE_STATE_MAX_GROUPS", 2048)
    monkeypatch.setattr(group_state, "PROACTIVE_STATE_TTL_SECONDS", 10.0)
    monkeypatch.setattr(group_state, "_proactive_next_prune_at", 100.0)

    group_state._proactive_last_seen["expired"] = 1.0
    group_state.get_proactive_cooldowns()["expired"] = 1.0
    group_state.get_proactive_message_counts()["expired"] = 1

    group_state.touch_proactive_group("g1", now=50.0)
    assert "expired" in group_state._proactive_last_seen

    group_state.touch_proactive_group("g1", now=101.0)
    assert "expired" not in group_state._proactive_last_seen
