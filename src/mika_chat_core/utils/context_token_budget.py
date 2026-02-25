"""Context token budget resolver (AstrBot-like, but stability-first).

This project stores lots of group history; blindly sending everything upstream can
cause provider/proxy endpoints to return empty/fallback responses even with HTTP 200.

Policy:
- If user sets `mika_context_max_tokens_soft > 0`, use it as-is.
- If `mika_context_max_tokens_soft <= 0`, treat it as "auto":
  1) Guess model context window by model id (best-effort).
  2) Use 82% of that window as the soft budget (AstrBot default threshold).
  3) Clamp to a conservative max budget to avoid huge request bodies.

Users can always override by setting an explicit positive number.
"""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import urlparse


AUTO_USAGE_RATIO: float = 0.82
AUTO_FALLBACK_TOKENS: int = 12_000
AUTO_MIN_TOKENS: int = 4_000

# Default cap: modern models can comfortably handle 100k context, and it's a
# practical baseline for "300 turns" chatrooms. Users can always override.
AUTO_MAX_TOKENS: int = 100_000

# Proxy cap: keep aligned with AUTO_MAX_TOKENS by default. If a proxy endpoint
# can't handle large requests, users should set an explicit smaller budget via
# `MIKA_CONTEXT_MAX_TOKENS_SOFT`.
AUTO_PROXY_MAX_TOKENS: int = 100_000


def _is_trusted_endpoint(*, provider: str, base_url: str) -> bool:
    """Heuristic: detect whether the endpoint is likely an official or local LLM endpoint.

    Third-party OpenAI-compatible proxies often impose smaller request-body limits.
    In auto mode we default to a more conservative cap unless the user explicitly overrides.
    """
    try:
        parsed = urlparse(str(base_url or "").strip())
        host = str(parsed.hostname or "").lower()
        path = str(parsed.path or "").lower()
    except Exception:
        host = ""
        path = ""

    if host in {"localhost", "127.0.0.1", "::1"}:
        return True

    provider_name = str(provider or "").strip().lower()
    if provider_name == "google_genai":
        return "generativelanguage.googleapis.com" in host
    if provider_name == "anthropic":
        return host.endswith("anthropic.com")
    if provider_name == "azure_openai":
        return "openai.azure.com" in host

    # openai_compat: treat official OpenAI + Google OpenAI-compat endpoints as trusted.
    if host.endswith("openai.com"):
        return True
    if "generativelanguage.googleapis.com" in host and "/openai" in path:
        return True
    return False


def guess_model_context_limit_tokens(model: str) -> int:
    """Best-effort guess of model context window size in tokens.

    We intentionally keep this coarse. The auto budget is clamped to `AUTO_MAX_TOKENS`,
    so exactness here is not critical for large-context models.
    """
    value = str(model or "").strip().lower()
    if not value:
        return 0

    # Gemini models generally have very large context windows.
    if "gemini" in value:
        return 1_048_576

    # Anthropic Claude models are commonly 200k context.
    if value.startswith("claude"):
        return 200_000

    # Common OpenAI families.
    if value.startswith(("gpt-4o", "gpt-4.1", "gpt-4-turbo")):
        return 128_000
    if value.startswith("gpt-3.5"):
        return 16_000

    return 0


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def resolve_context_max_tokens_soft(
    plugin_cfg: Any,
    *,
    models: Iterable[str] = (),
) -> int:
    """Resolve effective `max_tokens_soft` for request-time context trimming."""
    raw = _coerce_int(getattr(plugin_cfg, "mika_context_max_tokens_soft", AUTO_FALLBACK_TOKENS), AUTO_FALLBACK_TOKENS)
    if raw > 0:
        return raw

    provider = str(getattr(plugin_cfg, "llm_provider", "") or "").strip()
    base_url = str(getattr(plugin_cfg, "llm_base_url", "") or "").strip()
    endpoint_cap = AUTO_MAX_TOKENS if _is_trusted_endpoint(provider=provider, base_url=base_url) else min(AUTO_MAX_TOKENS, AUTO_PROXY_MAX_TOKENS)

    model_candidates = [str(m or "").strip() for m in (models or []) if str(m or "").strip()]
    if not model_candidates:
        model_candidates = [str(getattr(plugin_cfg, "llm_model", "") or "").strip()]

    guessed_limits: list[int] = []
    for model in model_candidates:
        limit = guess_model_context_limit_tokens(model)
        if limit > 0:
            guessed_limits.append(limit)

    limit_tokens = min(guessed_limits) if guessed_limits else 0
    if limit_tokens <= 0:
        return AUTO_FALLBACK_TOKENS

    budget = int(limit_tokens * AUTO_USAGE_RATIO)
    budget = max(AUTO_MIN_TOKENS, budget)
    budget = min(endpoint_cap, budget)
    return budget
