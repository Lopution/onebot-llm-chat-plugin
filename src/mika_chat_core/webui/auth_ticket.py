"""Short-lived ticket authentication for URL-only channels (SSE, WS, download).

Tickets replace raw token-in-URL for channels where ``Authorization`` headers
are not supported (``EventSource``, ``<a href>`` download, ``WebSocket``).

Each ticket is single-use by default and expires after a configurable TTL.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

log = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 60
_DEFAULT_MAX_ACTIVE = 50


@dataclass
class _TicketEntry:
    scope: str
    client_host: str
    created_at: float
    ttl_seconds: float
    single_use: bool


class TicketStore:
    """In-memory ticket store with TTL and optional single-use enforcement."""

    def __init__(
        self,
        *,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        single_use: bool = True,
        max_active: int = _DEFAULT_MAX_ACTIVE,
    ) -> None:
        self._ttl_seconds = max(5, ttl_seconds)
        self._single_use = single_use
        self._max_active = max(1, max_active)
        self._tickets: dict[str, _TicketEntry] = {}
        self._lock = Lock()

    def issue(self, scope: str, client_host: str = "") -> tuple[str, float]:
        """Issue a new ticket. Returns ``(ticket, expires_at_monotonic)``."""
        self._purge_expired()
        ticket = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            # Evict oldest when at capacity
            while len(self._tickets) >= self._max_active:
                oldest_key = min(self._tickets, key=lambda k: self._tickets[k].created_at)
                del self._tickets[oldest_key]
            self._tickets[ticket] = _TicketEntry(
                scope=scope,
                client_host=client_host,
                created_at=now,
                ttl_seconds=self._ttl_seconds,
                single_use=self._single_use,
            )
        return ticket, now + self._ttl_seconds

    def consume(self, ticket: str, scope: str, client_host: str = "") -> bool:
        """Validate and optionally consume a ticket. Returns ``True`` if valid."""
        self._purge_expired()
        with self._lock:
            entry = self._tickets.get(ticket)
            if entry is None:
                return False
            now = time.monotonic()
            if now - entry.created_at > entry.ttl_seconds:
                del self._tickets[ticket]
                return False
            if entry.scope != scope:
                return False
            if entry.client_host and client_host and entry.client_host != client_host:
                return False
            if entry.single_use:
                del self._tickets[ticket]
            return True

    def _purge_expired(self) -> None:
        now = time.monotonic()
        with self._lock:
            expired = [
                k for k, v in self._tickets.items() if now - v.created_at > v.ttl_seconds
            ]
            for k in expired:
                del self._tickets[k]

    @property
    def active_count(self) -> int:
        self._purge_expired()
        return len(self._tickets)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: Optional[TicketStore] = None


def get_ticket_store() -> TicketStore:
    global _store
    if _store is None:
        _store = TicketStore()
    return _store


def configure_ticket_store(
    *,
    ttl_seconds: float = _DEFAULT_TTL_SECONDS,
    single_use: bool = True,
    max_active: int = _DEFAULT_MAX_ACTIVE,
) -> TicketStore:
    """(Re)create the global ticket store with given settings."""
    global _store
    _store = TicketStore(
        ttl_seconds=ttl_seconds,
        single_use=single_use,
        max_active=max_active,
    )
    return _store


__all__ = [
    "TicketStore",
    "configure_ticket_store",
    "get_ticket_store",
]
