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
        now = time.time()
        if group_id not in self._group_logs:
            self._group_logs[group_id] = deque()
        self._group_logs[group_id].append(now)
        self._clean_old_logs(group_id, now)

    def get_heat(self, group_id: str) -> int:
        now = time.time()
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

# 冷却时间记录 {group_id: last_trigger_timestamp}
_proactive_cooldowns: Dict[str, float] = {}

# 消息条数计数器 {group_id: message_count_since_last_proactive}
_proactive_message_counts: Dict[str, int] = {}


def get_proactive_cooldowns() -> Dict[str, float]:
    return _proactive_cooldowns


def get_proactive_message_counts() -> Dict[str, int]:
    return _proactive_message_counts
