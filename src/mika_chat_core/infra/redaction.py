"""Sensitive data redaction for logs."""

from __future__ import annotations

import re

_REDACTION_TOKEN = "[REDACTED]"

_SENSITIVE_QUERY = re.compile(
    r"(?i)([?&](?:api(?:_|-)?key|key|token|access(?:_|-)?token|x-mika-core-token|x-mika-webui-token)=)([^&#\s]+)"
)
_SENSITIVE_BEARER = re.compile(
    r"(?i)(\b(?:authorization|proxy-authorization)\b\s*[:=]\s*(?:\"|')?bearer\s+)([A-Za-z0-9._~+/=-]+)"
)
_SENSITIVE_KV = re.compile(
    r"(?i)((?:\"|')?(?:api(?:_|-)?key|token|access(?:_|-)?token|x-api-key|x-mika-core-token|x-mika-webui-token)(?:\"|')?\s*[:=]\s*(?:\"|')?)([^\"'\s,;]+)"
)


def redact_sensitive_text(value: str) -> str:
    text = str(value or "")
    if not text:
        return text

    redacted = _SENSITIVE_QUERY.sub(r"\1" + _REDACTION_TOKEN, text)
    redacted = _SENSITIVE_BEARER.sub(r"\1" + _REDACTION_TOKEN, redacted)
    redacted = _SENSITIVE_KV.sub(r"\1" + _REDACTION_TOKEN, redacted)
    return redacted

