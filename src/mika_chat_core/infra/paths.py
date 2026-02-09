"""Path resolution helpers for host-agnostic core modules."""

from __future__ import annotations

import os
from pathlib import Path

from ..runtime import get_paths_port
from .logging import logger as log

_PROJECT_ROOT = Path(__file__).resolve().parents[4]


def get_data_root(namespace: str = "gemini_chat") -> Path:
    """Resolve writable data root for a namespace."""
    env_data_dir = os.getenv("GEMINI_DATA_DIR")
    if env_data_dir:
        return Path(env_data_dir) / namespace

    port = get_paths_port()
    if port is not None:
        try:
            path = port.get_data_dir(namespace)
            if path:
                return Path(path)
        except Exception as exc:
            log.warning(f"paths_port.get_data_dir failed, fallback to project data dir: {exc}")

    return _PROJECT_ROOT / "data" / namespace


def get_cache_root(namespace: str = "gemini_chat") -> Path:
    """Resolve writable cache root for a namespace."""
    port = get_paths_port()
    if port is not None:
        try:
            path = port.get_cache_dir(namespace)
            if path:
                return Path(path)
        except Exception as exc:
            log.warning(f"paths_port.get_cache_dir failed, fallback to project cache dir: {exc}")

    return _PROJECT_ROOT / "data" / namespace

