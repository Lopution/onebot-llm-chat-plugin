from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mika_chat_core.config import Config
from mika_chat_core.health_probe import get_cached_api_probe, reset_api_probe_cache


def _make_config(**overrides: object) -> Config:
    payload: dict[str, object] = {
        "mika_master_id": "1",
        "llm_api_key": "A" * 32,
        "mika_health_check_api_probe_enabled": True,
        "mika_health_check_api_probe_ttl_seconds": 30,
    }
    payload.update(overrides)
    return Config(**payload)


@pytest.mark.asyncio
async def test_get_cached_api_probe_returns_disabled_when_switch_off():
    reset_api_probe_cache()
    config = _make_config(mika_health_check_api_probe_enabled=False)
    result = await get_cached_api_probe(config)
    assert result["status"] == "disabled"
    assert result["cached"] is True


@pytest.mark.asyncio
async def test_get_cached_api_probe_uses_cache_within_ttl():
    reset_api_probe_cache()
    config = _make_config(mika_health_check_api_probe_enabled=True, mika_health_check_api_probe_ttl_seconds=60)

    with patch(
        "mika_chat_core.health_probe.probe_api_health_once",
        AsyncMock(return_value={"status": "healthy", "detail": "ok", "latency_ms": 1.5}),
    ) as mocked_probe:
        first = await get_cached_api_probe(config)
        second = await get_cached_api_probe(config)

    assert mocked_probe.await_count == 1
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["status"] == "healthy"

