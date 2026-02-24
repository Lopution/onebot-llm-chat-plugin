"""Centralized error handling policy.

Provides ``swallow()`` — a unified "best-effort" error policy that
replaces raw ``except Exception: pass`` patterns across the codebase.

Usage::

    from mika_chat_core.error_policy import swallow

    try:
        do_something()
    except Exception:
        swallow("do_something failed", exc_info=True)
"""

from __future__ import annotations

from .infra.logging import logger as _log


def swallow(msg: str, *, exc_info: bool = False) -> None:
    """Log a swallowed exception at DEBUG level.

    Call this inside ``except Exception`` blocks that intentionally
    suppress errors.  It keeps the suppression explicit and visible
    in debug logs without polluting normal output.
    """
    _log.debug(msg, exc_info=exc_info)
