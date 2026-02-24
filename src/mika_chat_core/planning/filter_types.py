"""Types for relevance filtering."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FilterResult:
    """Relevance filter output."""

    should_reply: bool
    reasoning: str
    confidence: float = 0.0


__all__ = ["FilterResult"]
