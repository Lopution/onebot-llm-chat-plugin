"""时序指标存储（内存环形缓冲）。"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Deque, Dict, List, Tuple


@dataclass
class _LlmEvent:
    timestamp: float
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class MetricsTimelineStore:
    def __init__(self, *, max_points: int = 50000, max_age_seconds: int = 7 * 24 * 3600) -> None:
        self._max_points = max(1000, int(max_points))
        self._max_age_seconds = max(3600, int(max_age_seconds))
        self._message_events: Deque[float] = deque(maxlen=self._max_points)
        self._llm_events: Deque[_LlmEvent] = deque(maxlen=self._max_points)
        self._lock = Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self._max_age_seconds
        while self._message_events and self._message_events[0] < cutoff:
            self._message_events.popleft()
        while self._llm_events and self._llm_events[0].timestamp < cutoff:
            self._llm_events.popleft()

    def record_message(self, *, timestamp: float | None = None) -> None:
        now = float(timestamp if timestamp is not None else time.time())
        with self._lock:
            self._message_events.append(now)
            self._prune(now)

    def record_llm(
        self,
        *,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        timestamp: float | None = None,
    ) -> None:
        now = float(timestamp if timestamp is not None else time.time())
        item = _LlmEvent(
            timestamp=now,
            latency_ms=max(0.0, float(latency_ms)),
            prompt_tokens=max(0, int(prompt_tokens or 0)),
            completion_tokens=max(0, int(completion_tokens or 0)),
            total_tokens=max(0, int(total_tokens or 0)),
        )
        with self._lock:
            self._llm_events.append(item)
            self._prune(now)

    @staticmethod
    def _percentile(values: List[float], ratio: float) -> float:
        if not values:
            return 0.0
        safe_ratio = min(max(ratio, 0.0), 1.0)
        ordered = sorted(values)
        index = int(round((len(ordered) - 1) * safe_ratio))
        return float(ordered[index])

    def get_timeseries(self, *, hours: int = 24, bucket_seconds: int = 3600) -> Dict[str, object]:
        safe_hours = max(1, min(int(hours or 24), 168))
        safe_bucket = max(60, min(int(bucket_seconds or 3600), 24 * 3600))
        now = time.time()
        start = now - safe_hours * 3600
        aligned_start = int(start // safe_bucket) * safe_bucket
        bucket_count = int(((now - aligned_start) // safe_bucket) + 1)
        if bucket_count <= 0:
            bucket_count = 1

        message_counts = [0 for _ in range(bucket_count)]
        llm_latencies: List[List[float]] = [[] for _ in range(bucket_count)]
        prompt_tokens = [0 for _ in range(bucket_count)]
        completion_tokens = [0 for _ in range(bucket_count)]
        total_tokens = [0 for _ in range(bucket_count)]

        with self._lock:
            self._prune(now)
            message_events = list(self._message_events)
            llm_events = list(self._llm_events)

        for timestamp in message_events:
            if timestamp < aligned_start:
                continue
            idx = int((timestamp - aligned_start) // safe_bucket)
            if 0 <= idx < bucket_count:
                message_counts[idx] += 1

        for event in llm_events:
            if event.timestamp < aligned_start:
                continue
            idx = int((event.timestamp - aligned_start) // safe_bucket)
            if 0 <= idx < bucket_count:
                llm_latencies[idx].append(float(event.latency_ms))
                prompt_tokens[idx] += int(event.prompt_tokens)
                completion_tokens[idx] += int(event.completion_tokens)
                total_tokens[idx] += int(event.total_tokens)

        points: List[Dict[str, object]] = []
        for idx in range(bucket_count):
            bucket_start = aligned_start + idx * safe_bucket
            latencies = llm_latencies[idx]
            points.append(
                {
                    "timestamp": float(bucket_start),
                    "messages": int(message_counts[idx]),
                    "llm_count": int(len(latencies)),
                    "llm_p50_ms": round(self._percentile(latencies, 0.50), 2),
                    "llm_p95_ms": round(self._percentile(latencies, 0.95), 2),
                    "prompt_tokens": int(prompt_tokens[idx]),
                    "completion_tokens": int(completion_tokens[idx]),
                    "total_tokens": int(total_tokens[idx]),
                }
            )

        return {
            "hours": safe_hours,
            "bucket_seconds": safe_bucket,
            "points": points,
        }


_metrics_timeline_store: MetricsTimelineStore | None = None


def get_metrics_timeline_store() -> MetricsTimelineStore:
    global _metrics_timeline_store
    if _metrics_timeline_store is None:
        _metrics_timeline_store = MetricsTimelineStore()
    return _metrics_timeline_store

