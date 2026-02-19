"""WebUI dashboard APIs."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict

import httpx
from fastapi import APIRouter, Depends

from ..config import Config
from ..llm.providers import build_provider_request
from ..metrics import metrics
from ..infra.metrics_store import get_metrics_timeline_store
from ..runtime import (
    get_client as get_runtime_client,
    get_config as get_runtime_config,
)
from ..utils.context_db import get_db
from ..utils.context_store import get_context_store
from ..utils.semantic_matcher import semantic_matcher
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper

PLUGIN_VERSION = "1.0.0"
HEALTH_PROBE_MAX_TOKENS = 1


async def _probe_api_health_once(config: Config) -> Dict[str, Any]:
    observability = config.get_observability_config()
    if not bool(observability.get("health_api_probe_enabled", False)):
        return {
            "status": "disabled",
            "detail": "probe_disabled",
            "latency_ms": 0.0,
        }

    llm_cfg = config.get_llm_config()
    api_keys = list(llm_cfg.get("api_keys") or [])
    if not api_keys:
        return {"status": "no_api_key", "detail": "no_effective_api_key", "latency_ms": 0.0}

    key = str(api_keys[0] or "").strip()
    if not key:
        return {"status": "no_api_key", "detail": "empty_api_key", "latency_ms": 0.0}

    base_url = str(llm_cfg.get("base_url") or config.llm_base_url).rstrip("/")
    provider_name = str(llm_cfg.get("provider") or "openai_compat")
    model_name = str(llm_cfg.get("fast_model") or llm_cfg.get("model") or config.llm_model)
    extra_headers = dict(llm_cfg.get("extra_headers") or {})
    timeout_seconds = float(observability.get("health_api_probe_timeout_seconds") or 3.0)

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
        if response.status_code == 200:
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


def create_dashboard_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/dashboard",
        tags=["mika-webui-dashboard"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.get("/health")
    async def dashboard_health() -> Dict[str, Any]:
        config = settings_getter()

        try:
            db = await get_db()
            await db.execute("SELECT 1")
            db_status = "connected"
        except Exception:
            db_status = "disconnected"

        try:
            client_status = "ready" if get_runtime_client() is not None else "not_initialized"
        except Exception:
            client_status = "not_initialized"
        api_probe = await _probe_api_health_once(config)

        overall_status = "healthy"
        if db_status != "connected" or client_status != "ready":
            overall_status = "degraded"
        if api_probe.get("status") not in {"healthy", "disabled"}:
            overall_status = "degraded"

        return BaseRouteHelper.ok(
            {
                "status": overall_status,
                "database": db_status,
                "mika_client": client_status,
                "api_probe": api_probe,
                "version": PLUGIN_VERSION,
            }
        )

    @router.get("/metrics")
    async def dashboard_metrics() -> Dict[str, Any]:
        return BaseRouteHelper.ok(metrics.snapshot())

    @router.get("/stats")
    async def dashboard_stats() -> Dict[str, Any]:
        config = settings_getter()

        memory_count = 0
        knowledge_count = 0
        context_stats: Dict[str, Any] = {}

        try:
            context_stats = await get_context_store().get_stats()
        except Exception as exc:
            context_stats = {"error": str(exc)}

        try:
            from ..utils.memory_store import get_memory_store

            store = get_memory_store()
            await store.init_table()
            memory_count = int(await store.count())
        except Exception:
            memory_count = 0

        try:
            from ..utils.knowledge_store import get_knowledge_store

            store = get_knowledge_store()
            await store.init_table()
            knowledge_count = int(await store.count())
        except Exception:
            knowledge_count = 0

        return BaseRouteHelper.ok(
            {
                "memory_count": memory_count,
                "knowledge_count": knowledge_count,
                "context_stats": context_stats,
                "semantic_model_status": {
                    "loaded": semantic_matcher._model is not None,  # noqa: SLF001
                    "backend": semantic_matcher._backend,  # noqa: SLF001
                    "model_name": str(getattr(config, "mika_semantic_model", "") or ""),
                },
                "version": PLUGIN_VERSION,
            },
        )

    @router.get("/timeline")
    async def dashboard_timeline(hours: int = 24, bucket_seconds: int = 3600) -> Dict[str, Any]:
        timeline = get_metrics_timeline_store().get_timeseries(
            hours=hours,
            bucket_seconds=bucket_seconds,
        )
        return BaseRouteHelper.ok(timeline)

    return router


__all__ = ["create_dashboard_router"]
