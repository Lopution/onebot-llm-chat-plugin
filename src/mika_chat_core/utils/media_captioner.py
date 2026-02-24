"""Media caption fallback service.

When the main upstream provider cannot accept image inputs, we can (optionally)
send the image to a caption-capable provider and inject the generated captions
into the request as *untrusted* context.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Mapping, Optional

import httpx

from ..infra.logging import logger as log
from ..llm.providers import build_provider_request, get_provider_capabilities, parse_provider_response
from .image_processor import ImageProcessError, get_image_processor
from .media_semantics import extract_media_semantic


_CACHE_TTL_SECONDS = 24 * 60 * 60  # 1 day
_CACHE_MAX_ITEMS = 1000
_caption_cache: dict[str, tuple[float, str]] = {}


def _now() -> float:
    return time.time()


def _cache_get(key: str) -> Optional[str]:
    item = _caption_cache.get(key)
    if not item:
        return None
    ts, value = item
    if _now() - ts > _CACHE_TTL_SECONDS:
        _caption_cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    if len(_caption_cache) >= _CACHE_MAX_ITEMS:
        try:
            oldest_key = min(_caption_cache.keys(), key=lambda k: _caption_cache[k][0])
            _caption_cache.pop(oldest_key, None)
        except Exception:
            _caption_cache.clear()
    _caption_cache[key] = (_now(), text)


def _extract_image_url(part: Mapping[str, Any]) -> str:
    image_url = part.get("image_url")
    if isinstance(image_url, Mapping):
        return str(image_url.get("url") or "").strip()
    return str(image_url or "").strip()


def _cache_key_for_part(part: Mapping[str, Any]) -> str:
    semantic = extract_media_semantic(part)
    media_kind = str(semantic.get("kind") or "").strip().lower()
    media_id = str(semantic.get("id") or "").strip()
    if media_id:
        return f"{media_kind}:{media_id}"
    url = _extract_image_url(part)
    digest = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()
    return f"url:{digest}"


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").lower() != "text":
                continue
            text = str(item.get("text") or "").strip()
            if text:
                chunks.append(text)
        return "\n".join(chunks).strip()
    return ""


async def _ensure_data_url(url: str, *, cfg: Any) -> Optional[str]:
    raw = str(url or "").strip()
    if not raw:
        return None
    if raw.startswith("data:"):
        return raw
    if not raw.startswith(("http://", "https://")):
        return None
    processor = get_image_processor(int(getattr(cfg, "mika_image_download_concurrency", 3) or 3))
    base64_data, mime_type = await processor.download_and_encode(raw)
    return f"data:{mime_type};base64,{base64_data}"


def _resolve_llm_cfg(cfg: Any) -> dict[str, Any]:
    if hasattr(cfg, "get_llm_config") and callable(getattr(cfg, "get_llm_config")):
        try:
            resolved = cfg.get_llm_config()
            if isinstance(resolved, dict):
                return resolved
        except Exception:
            pass
    api_keys: list[str] = []
    first_key = str(getattr(cfg, "llm_api_key", "") or "").strip()
    if first_key:
        api_keys.append(first_key)
    for item in (getattr(cfg, "llm_api_key_list", []) or []):
        key = str(item or "").strip()
        if key:
            api_keys.append(key)
    return {
        "provider": str(getattr(cfg, "llm_provider", "openai_compat") or "openai_compat").strip().lower(),
        "base_url": str(getattr(cfg, "llm_base_url", "") or "").strip().rstrip("/"),
        "model": str(getattr(cfg, "llm_model", "") or "").strip(),
        "fast_model": str(getattr(cfg, "llm_fast_model", "") or "").strip(),
        "api_keys": api_keys,
        "extra_headers": {},
    }


async def caption_images(
    image_parts: list[dict],
    *,
    request_id: str,
    cfg: Any,
) -> list[str]:
    """Caption images/memes into short text.

    Returns a list of caption texts (best-effort). Failures are logged and
    skipped, so callers should treat output as optional.
    """

    if not image_parts:
        return []

    llm_cfg = _resolve_llm_cfg(cfg)

    provider = str(getattr(cfg, "mika_media_caption_provider", "") or "").strip().lower() or str(
        llm_cfg.get("provider") or "openai_compat"
    ).strip().lower()
    base_url = str(getattr(cfg, "mika_media_caption_base_url", "") or "").strip() or str(
        llm_cfg.get("base_url") or getattr(cfg, "llm_base_url", "")
    ).strip()

    primary_key = ""
    api_keys = llm_cfg.get("api_keys") or []
    if isinstance(api_keys, list) and api_keys:
        primary_key = str(api_keys[0] or "").strip()
    api_key = str(getattr(cfg, "mika_media_caption_api_key", "") or "").strip() or primary_key

    model = str(getattr(cfg, "mika_media_caption_model", "") or "").strip() or str(
        llm_cfg.get("fast_model") or llm_cfg.get("model") or getattr(cfg, "llm_model", "")
    ).strip()

    prompt = str(getattr(cfg, "mika_media_caption_prompt", "") or "").strip()
    timeout_seconds = float(getattr(cfg, "mika_media_caption_timeout_seconds", 20.0) or 20.0)

    max_to_caption = int(getattr(cfg, "mika_history_image_two_stage_max", 2) or 2)
    max_to_caption = max(1, min(5, max_to_caption))

    caps = get_provider_capabilities(configured_provider=provider, base_url=base_url, model=model)
    if not bool(caps.supports_images):
        log.warning(
            f"[caption] provider does not support images, disabled | req={request_id} | provider={caps.provider}"
        )
        return []

    results: list[str] = []
    for index, part in enumerate(list(image_parts)[:max_to_caption]):
        if not isinstance(part, dict):
            continue
        cache_key = _cache_key_for_part(part)
        cached = _cache_get(cache_key)
        if cached:
            results.append(cached)
            continue

        url = _extract_image_url(part)
        try:
            data_url = await _ensure_data_url(url, cfg=cfg)
        except ImageProcessError as exc:
            log.warning(f"[caption] image download failed | req={request_id} | index={index} | err={exc}")
            continue
        except Exception as exc:
            log.warning(f"[caption] image process failed | req={request_id} | index={index} | err={exc}")
            continue

        if not data_url:
            continue

        user_content = [
            {"type": "text", "text": "请描述这张图/表情包。"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        request_body: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
        }

        prepared = build_provider_request(
            provider=provider,
            base_url=base_url,
            model=model,
            api_key=api_key,
            request_body=request_body,
            extra_headers=dict(llm_cfg.get("extra_headers") or {}),
            default_temperature=0.0,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                resp = await client.post(
                    prepared.url,
                    headers=prepared.headers,
                    params=prepared.params,
                    json=prepared.json_body,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            log.warning(f"[caption] request failed | req={request_id} | provider={prepared.provider} | err={exc}")
            continue

        try:
            assistant_message, _tool_calls, content, _finish = parse_provider_response(
                provider=prepared.provider,
                data=data if isinstance(data, dict) else {},
            )
        except Exception as exc:
            log.warning(f"[caption] parse failed | req={request_id} | provider={prepared.provider} | err={exc}")
            continue

        text = _content_to_text(content)
        if not text:
            text = _content_to_text(assistant_message.get("content") if isinstance(assistant_message, dict) else "")
        if not text:
            continue

        _cache_set(cache_key, text)
        results.append(text)

    return results

