"""Host event runtime port.

Adapter layers can map host events to envelopes and expose runtime references
through this protocol so core engine paths stay contracts/ports oriented.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, Tuple

from ..contracts import EventEnvelope


class HostEventPort(Protocol):
    def resolve_event(self, envelope: EventEnvelope) -> Optional[Tuple[Any, Any]]:
        ...
