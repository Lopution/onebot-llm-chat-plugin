from __future__ import annotations

from collections import deque
from typing import Deque, Dict
import time


class HeatMonitor:
    """群聊热度监测器"""

    def __init__(self, window_size: int = 60):
        self._group_logs: Dict[str, Deque[float]] = {}
        self._window_size = window_size

    def record_message(self, group_id: str) -> None:
        now = time.monotonic()
        if group_id not in self._group_logs:
            self._group_logs[group_id] = deque()
        self._group_logs[group_id].append(now)
        self._clean_old_logs(group_id, now)

    def get_heat(self, group_id: str) -> int:
        now = time.monotonic()
        self._clean_old_logs(group_id, now)
        return len(self._group_logs.get(group_id, []))

    def _clean_old_logs(self, group_id: str, now: float) -> None:
        logs = self._group_logs.get(group_id)
        if not logs:
            return
        threshold = now - self._window_size
        while logs and logs[0] < threshold:
            logs.popleft()


heat_monitor = HeatMonitor()

# 冷却时间记录 {group_id: last_trigger_monotonic}
_proactive_cooldowns: Dict[str, float] = {}

# 消息条数计数器 {group_id: message_count_since_last_proactive}
_proactive_message_counts: Dict[str, int] = {}

# 主动发言状态最后活跃时间（用于清理无界增长）
_proactive_last_seen: Dict[str, float] = {}

# 主动发言状态清理参数
PROACTIVE_STATE_MAX_GROUPS = 2048
PROACTIVE_STATE_TTL_SECONDS = 6 * 3600.0
PROACTIVE_STATE_PRUNE_INTERVAL_SECONDS = 60.0
_proactive_next_prune_at = 0.0


def get_proactive_cooldowns() -> Dict[str, float]:
    return _proactive_cooldowns


def get_proactive_message_counts() -> Dict[str, int]:
    return _proactive_message_counts


def prune_proactive_state(*, now: float | None = None) -> None:
    """清理长期不活跃的主动发言状态，避免字典无界增长。"""
    current = time.monotonic() if now is None else float(now)
    expire_before = current - PROACTIVE_STATE_TTL_SECONDS

    # 先按 TTL 清理
    for group_id, last_seen in list(_proactive_last_seen.items()):
        if last_seen < expire_before:
            _proactive_last_seen.pop(group_id, None)
            _proactive_cooldowns.pop(group_id, None)
            _proactive_message_counts.pop(group_id, None)

    # 再按数量上限清理（淘汰最旧）
    if len(_proactive_last_seen) <= PROACTIVE_STATE_MAX_GROUPS:
        return

    ordered = sorted(_proactive_last_seen.items(), key=lambda item: item[1])
    overflow = len(_proactive_last_seen) - PROACTIVE_STATE_MAX_GROUPS
    for group_id, _ in ordered[:overflow]:
        _proactive_last_seen.pop(group_id, None)
        _proactive_cooldowns.pop(group_id, None)
        _proactive_message_counts.pop(group_id, None)


def touch_proactive_group(group_id: str, *, now: float | None = None) -> None:
    """更新群组主动发言状态活跃时间并触发轻量清理。"""
    global _proactive_next_prune_at

    group_key = str(group_id or "").strip()
    if not group_key:
        return
    current = time.monotonic() if now is None else float(now)
    _proactive_last_seen[group_key] = current

    should_prune = len(_proactive_last_seen) > PROACTIVE_STATE_MAX_GROUPS
    if not should_prune and current >= _proactive_next_prune_at:
        should_prune = True

    if not should_prune:
        return

    _proactive_next_prune_at = current + PROACTIVE_STATE_PRUNE_INTERVAL_SECONDS
    prune_proactive_state(now=current)
