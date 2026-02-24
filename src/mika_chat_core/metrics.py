"""插件指标统计模块。

提供插件运行时的统计指标收集，用于监控和调试：
- API 请求计数
- 工具调用统计
- 搜索缓存命中率
- 图片缓存命中率
- 主动发言触发统计
- 历史图片上下文增强统计

通过全局 metrics 实例访问所有指标。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Metrics:
    """插件运行时指标数据类。

    Attributes:
        requests_total: API 请求总数
        tool_calls_total: 工具调用总数
        tool_blocked_total: 工具调用被阻止次数
        search_requests_total: 搜索请求总数
        search_cache_hit_total: 搜索缓存命中次数
        search_cache_miss_total: 搜索缓存未命中次数
        image_cache_hit_total: 图片缓存命中次数
        image_cache_miss_total: 图片缓存未命中次数
        proactive_trigger_total: 主动发言触发次数
        proactive_reject_total: 主动发言拒绝次数
    """
    requests_total: int = 0
    tool_calls_total: int = 0
    tool_blocked_total: int = 0
    search_requests_total: int = 0
    search_cache_hit_total: int = 0
    search_cache_miss_total: int = 0
    image_cache_hit_total: int = 0
    image_cache_miss_total: int = 0
    proactive_trigger_total: int = 0
    proactive_reject_total: int = 0
    # 历史图片上下文增强相关指标
    history_image_inline_used_total: int = 0
    history_image_two_stage_triggered_total: int = 0
    history_image_collage_used_total: int = 0
    history_image_fetch_tool_success_total: int = 0
    history_image_fetch_tool_fail_total: int = 0
    history_image_fetch_tool_source_cache_total: int = 0
    history_image_fetch_tool_source_archive_total: int = 0
    history_image_fetch_tool_source_get_msg_total: int = 0
    history_image_images_injected_total: int = 0
    api_empty_reply_total: int = 0
    api_empty_reply_reason_total: Dict[str, int] = field(default_factory=dict)
    api_transport_error_total: Dict[str, int] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, object]:
        return {
            "requests_total": self.requests_total,
            "tool_calls_total": self.tool_calls_total,
            "tool_blocked_total": self.tool_blocked_total,
            "search_requests_total": self.search_requests_total,
            "search_cache_hit_total": self.search_cache_hit_total,
            "search_cache_miss_total": self.search_cache_miss_total,
            "image_cache_hit_total": self.image_cache_hit_total,
            "image_cache_miss_total": self.image_cache_miss_total,
            "proactive_trigger_total": self.proactive_trigger_total,
            "proactive_reject_total": self.proactive_reject_total,
            "history_image_inline_used_total": self.history_image_inline_used_total,
            "history_image_two_stage_triggered_total": self.history_image_two_stage_triggered_total,
            "history_image_collage_used_total": self.history_image_collage_used_total,
            "history_image_fetch_tool_success_total": self.history_image_fetch_tool_success_total,
            "history_image_fetch_tool_fail_total": self.history_image_fetch_tool_fail_total,
            "history_image_fetch_tool_source_cache_total": self.history_image_fetch_tool_source_cache_total,
            "history_image_fetch_tool_source_archive_total": self.history_image_fetch_tool_source_archive_total,
            "history_image_fetch_tool_source_get_msg_total": self.history_image_fetch_tool_source_get_msg_total,
            "history_image_images_injected_total": self.history_image_images_injected_total,
            "api_empty_reply_total": self.api_empty_reply_total,
            "api_empty_reply_reason_total": dict(self.api_empty_reply_reason_total),
            "api_transport_error_total": dict(self.api_transport_error_total),
        }

    @staticmethod
    def _escape_label_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")

    def to_prometheus(self, *, namespace: str = "mika_chat", plugin_version: str = "") -> str:
        """导出 Prometheus 文本格式（OpenMetrics 0.0.4 兼容）。"""
        metric_prefix = f"{namespace}_"
        lines = []

        simple_counters = {
            "requests_total": self.requests_total,
            "tool_calls_total": self.tool_calls_total,
            "tool_blocked_total": self.tool_blocked_total,
            "search_requests_total": self.search_requests_total,
            "search_cache_hit_total": self.search_cache_hit_total,
            "search_cache_miss_total": self.search_cache_miss_total,
            "image_cache_hit_total": self.image_cache_hit_total,
            "image_cache_miss_total": self.image_cache_miss_total,
            "proactive_trigger_total": self.proactive_trigger_total,
            "proactive_reject_total": self.proactive_reject_total,
            "history_image_inline_used_total": self.history_image_inline_used_total,
            "history_image_two_stage_triggered_total": self.history_image_two_stage_triggered_total,
            "history_image_collage_used_total": self.history_image_collage_used_total,
            "history_image_fetch_tool_success_total": self.history_image_fetch_tool_success_total,
            "history_image_fetch_tool_fail_total": self.history_image_fetch_tool_fail_total,
            "history_image_fetch_tool_source_cache_total": self.history_image_fetch_tool_source_cache_total,
            "history_image_fetch_tool_source_archive_total": self.history_image_fetch_tool_source_archive_total,
            "history_image_fetch_tool_source_get_msg_total": self.history_image_fetch_tool_source_get_msg_total,
            "history_image_images_injected_total": self.history_image_images_injected_total,
            "api_empty_reply_total": self.api_empty_reply_total,
        }

        for name, value in simple_counters.items():
            full = f"{metric_prefix}{name}"
            lines.append(f"# TYPE {full} counter")
            lines.append(f"{full} {int(value)}")

        reason_metric = f"{metric_prefix}api_empty_reply_reason_total"
        lines.append(f"# TYPE {reason_metric} counter")
        for reason, count in sorted(self.api_empty_reply_reason_total.items()):
            escaped = self._escape_label_value(str(reason))
            lines.append(f'{reason_metric}{{reason="{escaped}"}} {int(count)}')

        transport_metric = f"{metric_prefix}api_transport_error_total"
        lines.append(f"# TYPE {transport_metric} counter")
        for reason, count in sorted(self.api_transport_error_total.items()):
            escaped = self._escape_label_value(str(reason))
            lines.append(f'{transport_metric}{{reason="{escaped}"}} {int(count)}')

        info_metric = f"{metric_prefix}build_info"
        lines.append(f"# TYPE {info_metric} gauge")
        version = self._escape_label_value(plugin_version or "unknown")
        lines.append(f'{info_metric}{{version="{version}"}} 1')

        return "\n".join(lines) + "\n"


metrics = Metrics()
