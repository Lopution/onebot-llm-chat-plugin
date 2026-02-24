"""Context store constants."""

# LRU memory cache
MAX_CACHE_SIZE: int = 200

# When trimming context, keep up to max_context * MULTIPLIER messages
CONTEXT_MESSAGE_MULTIPLIER: int = 2

# Nickname sanitization
NICKNAME_MAX_LENGTH: int = 12

# Key-info extraction field length bounds
KEY_INFO_IDENTITY_MIN_CHARS: int = 2
KEY_INFO_IDENTITY_MAX_CHARS: int = 10
KEY_INFO_OCCUPATION_MIN_CHARS: int = 2
KEY_INFO_OCCUPATION_MAX_CHARS: int = 15
KEY_INFO_PREFERENCE_MIN_CHARS: int = 2
KEY_INFO_PREFERENCE_MAX_CHARS: int = 20
KEY_INFO_EXTRACTED_VALUE_MIN_CHARS: int = 2
KEY_INFO_EXTRACTED_VALUE_MAX_CHARS: int = 20
