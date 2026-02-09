"""Host-agnostic runtime type aliases.

核心层不依赖宿主框架类型，统一在运行时使用 `Any` 占位。
具体宿主（NoneBot/Koishi 等）在适配层处理静态类型与运行时约束。
"""

from __future__ import annotations

from typing import Any, TypeAlias


BotT: TypeAlias = Any
EventT: TypeAlias = Any
