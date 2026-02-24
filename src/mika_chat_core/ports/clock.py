"""Clock capability port."""

from __future__ import annotations

from typing import Protocol


class ClockPort(Protocol):
    def now(self) -> float:
        ...

    def monotonic(self) -> float:
        ...
