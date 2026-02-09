"""Host path capability port.

Core modules use this protocol to obtain runtime data/cache directories
without importing host-specific packages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PathsPort(Protocol):
    def get_data_dir(self, namespace: str) -> Path:
        ...

    def get_cache_dir(self, namespace: str) -> Path:
        ...

