"""NoneBot localstore-backed path port implementation."""

from __future__ import annotations

from pathlib import Path

from nonebot_plugin_localstore import get_cache_dir, get_data_dir


class LocalstorePathsPort:
    def get_data_dir(self, namespace: str) -> Path:
        return Path(get_data_dir(namespace))

    def get_cache_dir(self, namespace: str) -> Path:
        return Path(get_cache_dir(namespace))

