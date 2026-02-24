"""Context store package.

Re-exports all public symbols from the sub-modules so that existing
``from mika_chat_core.utils.context_store import ...`` continues to work.
"""

from .store import (                                         # noqa: F401
    ContextStoreWriteError,
    DB_PATH,
    SQLiteContextStore,
    close_context_store,
    get_context_store,
    init_context_store,
)

# Re-export DB helpers that some callers use via context_store
from ..context_db import get_db, get_db_path, init_database, close_database  # noqa: F401

# Re-export write-path types
from .write_pipeline import AddMessageDeps, add_message_flow  # noqa: F401

# Re-export session queries
from .session_queries import (                               # noqa: F401
    clear_session,
    get_all_keys,
    get_session_stats,
    get_stats,
    list_sessions,
    preview_text,
)

# Re-export summary helpers
from .summary_service import (                               # noqa: F401
    build_key_info_summary,
    build_summary_for_messages,
    extract_key_info_from_history,
    get_cached_summary,
    resolve_summary_runtime_config,
    save_cached_summary,
)
