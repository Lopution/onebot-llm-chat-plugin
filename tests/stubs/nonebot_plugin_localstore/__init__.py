"""tests-only stub for nonebot_plugin_localstore."""

from __future__ import annotations

from pathlib import Path


def _root() -> Path:
    base = Path("/tmp") / "mika-localstore-stub"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_data_dir(namespace: str | None = None) -> Path:
    name = str(namespace or "default").strip() or "default"
    path = _root() / "data" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_dir(namespace: str | None = None) -> Path:
    name = str(namespace or "default").strip() or "default"
    path = _root() / "cache" / name
    path.mkdir(parents=True, exist_ok=True)
    return path
