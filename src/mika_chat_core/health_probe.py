"""Core-level API health probe utilities."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict

import httpx

from .config import Config
from .llm.providers import build_provider_request

HEALTH_PROBE_MAX_TOKENS = 1
API_VALIDATE_SUCCESS_STATUS = 200
BASE_URL_RSTRIP_CHAR = "/"


@dataclass
class _ApiProbeCacheState:
    checked_at: float = 0.0
    status: str = "unknown"
    detail: str = ""
    latency_ms: float = 0.0


_state = _ApiProbeCacheState()


def reset_api_probe_cache() -> None:
    _state.checked_at = 0.0
    _state.status = "unknown"
    _state.detail = ""
    _state.latency_ms = 0.0


async def probe_api_health_once(config: Config) -> Dict[str, Any]:
    """执行一次轻量 API 连通性探测。"""
    api_keys = config.get_effective_api_keys()
    if not api_keys:
        return {"status": "no_api_key", "detail": "no_effective_api_key", "latency_ms": 0.0}

    key = str(api_keys[0] or "").strip()
    if not key:
        return {"status": "no_api_key", "detail": "empty_api_key", "latency_ms": 0.0}

    llm_cfg = config.get_llm_config()
    base_url = str(llm_cfg.get("base_url") or config.llm_base_url).rstrip(BASE_URL_RSTRIP_CHAR)
    model_name = str(llm_cfg.get("fast_model") or llm_cfg.get("model") or config.llm_model)
    provider_name = str(llm_cfg.get("provider") or "openai_compat")
    extra_headers = dict(llm_cfg.get("extra_headers") or {})
    timeout_seconds = float(config.mika_health_check_api_probe_timeout_seconds)

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            prepared = build_provider_request(
                provider=provider_name,
                base_url=base_url,
                model=model_name,
                api_key=key,
                request_body={
                    "model": model_name,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": HEALTH_PROBE_MAX_TOKENS,
                    "temperature": 0,
                    "stream": False,
                },
                extra_headers=extra_headers,
                default_temperature=0.0,
            )
            response = await client.post(
                prepared.url,
                headers=prepared.headers,
                params=prepared.params,
                json=prepared.json_body,
            )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if response.status_code == API_VALIDATE_SUCCESS_STATUS:
            return {"status": "healthy", "detail": f"{provider_name}_ok", "latency_ms": latency_ms}
        return {
            "status": "degraded",
            "detail": f"http_{response.status_code}",
            "latency_ms": latency_ms,
        }
    except httpx.TimeoutException:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {"status": "timeout", "detail": "timeout_exception", "latency_ms": latency_ms}
    except httpx.ConnectError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {"status": "connect_error", "detail": str(exc), "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {"status": "error", "detail": f"{type(exc).__name__}:{exc}", "latency_ms": latency_ms}


async def get_cached_api_probe(config: Config) -> Dict[str, Any]:
    """返回缓存的 API 探测结果（过期时刷新）。"""
    observability = config.get_observability_config()
    if not bool(observability["health_api_probe_enabled"]):
        return {"status": "disabled", "detail": "probe_disabled", "latency_ms": 0.0, "cached": True}

    ttl_seconds = max(1, int(observability["health_api_probe_ttl_seconds"]))
    now = time.monotonic()
    checked_at = float(_state.checked_at or 0.0)
    if checked_at > 0 and (now - checked_at) < ttl_seconds:
        return {
            "status": str(_state.status),
            "detail": str(_state.detail),
            "latency_ms": float(_state.latency_ms or 0.0),
            "cached": True,
        }

    fresh = await probe_api_health_once(config)
    _state.checked_at = now
    _state.status = str(fresh.get("status", "unknown"))
    _state.detail = str(fresh.get("detail", ""))
    _state.latency_ms = float(fresh.get("latency_ms", 0.0) or 0.0)
    return {
        "status": _state.status,
        "detail": _state.detail,
        "latency_ms": _state.latency_ms,
        "cached": False,
    }
