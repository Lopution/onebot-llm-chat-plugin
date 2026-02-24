from __future__ import annotations

from mika_chat_core.infra.log_broker import get_log_broker
from mika_chat_core.infra.logging import logger
from mika_chat_core.infra.redaction import redact_sensitive_text


def test_redact_sensitive_text_masks_query_and_headers():
    raw = (
        "GET /v1/events?token=abc123&key=xyz789 "
        "Authorization: Bearer sk-secret-123 "
        "payload={'api_key':'visible'}"
    )
    sanitized = redact_sensitive_text(raw)
    assert "abc123" not in sanitized
    assert "xyz789" not in sanitized
    assert "sk-secret-123" not in sanitized
    assert "visible" not in sanitized
    assert "[REDACTED]" in sanitized


def test_logger_proxy_publishes_redacted_message():
    broker = get_log_broker()
    since = broker.next_id
    logger.info("probe url=/v1/events?token=plain-secret")
    events = broker.history(since_id=since, limit=1)
    assert events
    assert "plain-secret" not in events[0]["message"]
    assert "[REDACTED]" in events[0]["message"]

