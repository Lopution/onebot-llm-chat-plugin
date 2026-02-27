"""Request planning types.

This module defines a stable, inspectable plan object that explains
"what we decided to do for this request, and why".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


ReplyMode = Literal["direct", "tool_loop", "no_reply"]
MediaNeed = Literal["none", "caption", "images"]


@dataclass(frozen=True)
class RequestPlan:
    should_reply: bool
    reply_mode: ReplyMode
    need_media: MediaNeed

    use_memory_retrieval: bool
    use_ltm_memory: bool
    use_knowledge_auto_inject: bool

    tool_policy: dict[str, Any]

    reason: str
    confidence: float
    planner_mode: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Keep json-friendly and stable.
        data["confidence"] = float(self.confidence)
        return data


__all__ = ["RequestPlan", "ReplyMode", "MediaNeed"]

