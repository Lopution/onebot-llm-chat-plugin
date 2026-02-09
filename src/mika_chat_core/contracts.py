"""Host-agnostic contracts for future adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ChatMessage:
    role: str
    text: str
    user_id: str = ""
    group_id: str = ""
    message_id: str = ""
    mentions: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatSession:
    user_id: str
    group_id: Optional[str] = None
    is_private: bool = False

