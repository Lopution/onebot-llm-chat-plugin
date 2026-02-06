"""metrics 模块测试。"""

from __future__ import annotations

from gemini_chat.metrics import Metrics


def test_metrics_to_prometheus_basic():
    metrics = Metrics(
        requests_total=3,
        api_empty_reply_total=2,
        api_empty_reply_reason_total={"provider_empty": 2},
        api_transport_error_total={"timeout": 1},
    )

    text = metrics.to_prometheus(plugin_version="1.2.3")

    assert "# TYPE gemini_chat_requests_total counter" in text
    assert "gemini_chat_requests_total 3" in text
    assert 'gemini_chat_api_empty_reply_reason_total{reason="provider_empty"} 2' in text
    assert 'gemini_chat_api_transport_error_total{reason="timeout"} 1' in text
    assert 'gemini_chat_build_info{version="1.2.3"} 1' in text


def test_metrics_to_prometheus_escapes_labels():
    metrics = Metrics(
        api_empty_reply_reason_total={'line"break\\x': 1},
        api_transport_error_total={"a\nb": 2},
    )

    text = metrics.to_prometheus(plugin_version='v"1')

    assert '\\"' in text
    assert "\\\\" in text
    assert "\\n" in text
    assert 'gemini_chat_build_info{version="v\\"1"} 1' in text
