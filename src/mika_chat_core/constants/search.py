"""Search engine constants."""

# Result cache
CACHE_TTL_SECONDS: int = 60
MAX_CACHE_SIZE: int = 100

# Log formatting
QUERY_PREVIEW_CHARS: int = 30
SNIPPET_PREVIEW_CHARS: int = 100
LOG_SEPARATOR_WIDTH: int = 50

# Injection bounds
MIN_INJECTION_RESULTS: int = 1
MAX_INJECTION_RESULTS: int = 10
DEFAULT_INJECTION_RESULTS: int = 6
