"""Persona domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Persona:
    """Persona record stored in SQLite."""

    id: int
    name: str
    character_prompt: str
    dialogue_examples: List[Dict[str, Any]] = field(default_factory=list)
    error_messages: Dict[str, str] = field(default_factory=dict)
    is_active: bool = False
    temperature_override: float | None = None
    model_override: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": int(self.id),
            "name": str(self.name or "").strip(),
            "character_prompt": str(self.character_prompt or ""),
            "dialogue_examples": list(self.dialogue_examples or []),
            "error_messages": dict(self.error_messages or {}),
            "is_active": bool(self.is_active),
            "temperature_override": self.temperature_override,
            "model_override": str(self.model_override or "").strip(),
            "created_at": float(self.created_at or 0.0),
            "updated_at": float(self.updated_at or 0.0),
        }

