"""Request-scoped prompt context helpers."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Dict


_prompt_context_var: ContextVar[Dict[str, Any]] = ContextVar(
    "mika_prompt_context",
    default={},
)


def set_prompt_context(values: Dict[str, Any]) -> Token:
    """Set request-scoped prompt context and return reset token."""
    return _prompt_context_var.set(dict(values or {}))


def get_prompt_context() -> Dict[str, Any]:
    """Get current prompt context snapshot."""
    return dict(_prompt_context_var.get())


def update_prompt_context(values: Dict[str, Any]) -> Dict[str, Any]:
    """Merge values into current prompt context."""
    merged = dict(_prompt_context_var.get())
    merged.update(dict(values or {}))
    _prompt_context_var.set(merged)
    return dict(merged)


def reset_prompt_context(token: Token) -> None:
    """Reset prompt context to previous state."""
    _prompt_context_var.reset(token)


__all__ = [
    "get_prompt_context",
    "set_prompt_context",
    "update_prompt_context",
    "reset_prompt_context",
]

