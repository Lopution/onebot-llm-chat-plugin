"""Mika API - 初始化辅助逻辑。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, DefaultDict, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ContextBackendInitResult:
    use_persistent: bool
    context_store: Any
    contexts: DefaultDict[Tuple[str, str], List[Dict[str, Any]]]


def init_context_backend(
    *,
    use_persistent_storage: bool,
    has_sqlite_store: bool,
    max_context: int,
    plugin_cfg: Any,
    get_context_store_fn: Optional[Callable[..., Any]],
    log_obj: Any,
) -> ContextBackendInitResult:
    contexts: DefaultDict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    use_persistent = bool(use_persistent_storage and has_sqlite_store and callable(get_context_store_fn))
    if not use_persistent:
        log_obj.info("使用内存上下文存储")
        return ContextBackendInitResult(
            use_persistent=False,
            context_store=None,
            contexts=contexts,
        )

    cache_size = max(
        1,
        int(getattr(plugin_cfg, "mika_context_cache_max_size", 200) or 200),
    )
    context_store = get_context_store_fn(
        max_context,
        max_cache_size=cache_size,
        context_mode=str(getattr(plugin_cfg, "mika_context_mode", "structured")),
        max_turns=int(getattr(plugin_cfg, "mika_context_max_turns", 30) or 30),
        max_tokens_soft=int(
            getattr(plugin_cfg, "mika_context_max_tokens_soft", 12000) or 12000
        ),
        summary_enabled=bool(
            getattr(plugin_cfg, "mika_context_summary_enabled", False)
        ),
        summary_trigger_turns=int(
            getattr(plugin_cfg, "mika_context_summary_trigger_turns", 20) or 20
        ),
        summary_max_chars=int(
            getattr(plugin_cfg, "mika_context_summary_max_chars", 500) or 500
        ),
        history_store_multimodal=bool(
            getattr(plugin_cfg, "mika_history_store_multimodal", False)
        ),
    )
    log_obj.info("使用 SQLite 持久化上下文存储")
    return ContextBackendInitResult(
        use_persistent=True,
        context_store=context_store,
        contexts=contexts,
    )


def init_chat_history_summarizer(
    *,
    plugin_cfg: Any,
    get_chat_history_summarizer_fn: Callable[[], Any],
) -> Any:
    if bool(getattr(plugin_cfg, "mika_topic_summary_enabled", False)):
        return get_chat_history_summarizer_fn()
    return None
