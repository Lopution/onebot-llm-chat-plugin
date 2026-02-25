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


AUTO_USAGE_RATIO: float = 0.82
AUTO_FALLBACK_TOKENS: int = 12_000
AUTO_MIN_TOKENS: int = 4_000

# Safety-first cap: even if a model supports huge contexts, very large prompts are
# expensive and tend to be unstable through third-party proxies.
AUTO_MAX_TOKENS: int = 20_000


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
    budget = min(AUTO_MAX_TOKENS, budget)
    return budget

