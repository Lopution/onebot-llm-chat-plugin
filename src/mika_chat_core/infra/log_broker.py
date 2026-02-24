"""In-memory log broker for WebUI live log streaming."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Set


@dataclass(frozen=True)
class LogEvent:
    """Single brokered log entry."""

    id: int
    timestamp: float
    level: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
        }


class LogBroker:
    """Lightweight pub/sub broker with ring-buffer history."""

    def __init__(self, max_events: int = 500) -> None:
        self._events: Deque[LogEvent] = deque(maxlen=max(50, int(max_events or 500)))
        self._subscribers: Set[asyncio.Queue[LogEvent]] = set()
        self._next_id: int = 0

    @property
    def next_id(self) -> int:
        return self._next_id

    def publish(self, level: str, message: str) -> None:
        self._next_id += 1
        event = LogEvent(
            id=self._next_id,
            timestamp=time.time(),
            level=str(level or "INFO").upper(),
            message=str(message or "").strip(),
        )
        self._events.append(event)
        stale: List[asyncio.Queue[LogEvent]] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except Exception:
                stale.append(queue)
        for queue in stale:
            self._subscribers.discard(queue)

    def history(self, *, since_id: int = 0, limit: int = 200) -> List[Dict[str, Any]]:
        max_items = max(1, min(int(limit or 200), 1000))
        filtered = [event for event in self._events if event.id > int(since_id or 0)]
        if len(filtered) > max_items:
            filtered = filtered[-max_items:]
        return [item.to_dict() for item in filtered]

    def subscribe(self, *, max_queue_size: int = 200) -> asyncio.Queue[LogEvent]:
        queue: asyncio.Queue[LogEvent] = asyncio.Queue(maxsize=max(1, int(max_queue_size or 200)))
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[LogEvent]) -> None:
        self._subscribers.discard(queue)


_broker: LogBroker | None = None


def get_log_broker() -> LogBroker:
    global _broker
    if _broker is None:
        _broker = LogBroker()
    return _broker


__all__ = ["LogEvent", "LogBroker", "get_log_broker"]
