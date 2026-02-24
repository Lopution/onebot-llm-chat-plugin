"""Asset capability port."""

from __future__ import annotations

from typing import Protocol


class AssetPort(Protocol):
    async def download(self, asset_ref: str) -> bytes:
        ...
