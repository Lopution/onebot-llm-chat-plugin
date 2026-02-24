from __future__ import annotations

from mika_chat_core.utils.image_processor import _parse_data_url


def test_parse_data_url_valid_payload():
    parsed = _parse_data_url("data:image/png;base64,ZmFrZQ==")
    assert parsed == ("ZmFrZQ==", "image/png")


def test_parse_data_url_invalid_payload_returns_none():
    assert _parse_data_url("data:image/png;base64") is None
    assert _parse_data_url("data:,") is None
    assert _parse_data_url("https://example.com/image.png") is None
