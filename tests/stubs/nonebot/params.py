"""tests 专用 nonebot.params stub。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class Depends:
    dependency: Optional[Callable[..., Any]] = None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.dependency is None:
            return None
        return self.dependency(*args, **kwargs)

