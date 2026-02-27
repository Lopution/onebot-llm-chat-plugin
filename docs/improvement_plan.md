# 全量改进实施计划（性能/稳定性、可观测性、安全合规、体验）

!!! warning "ARCHIVED / 已归档"
    本文是历史计划文档，不再保证与当前代码一致（尤其是路径/模块名/配置键名）。
    
    - 项目总路线图：`docs/roadmap.md`
    - 长期架构方向：`docs/refactor_direction.md`

> 目标：在保持对外行为兼容的前提下，补齐可靠性、可观测性、安全控制与体验参数化，并最终更新 README 的“新增功能”说明。

## 1. 范围与影响面

- 核心聊天与工具链路：[`mika_api.py`](../src/mika_chat_core/mika_api.py)
- 工具调用处理：[`mika_api_tools.py`](../src/mika_chat_core/mika_api_tools.py)
- 搜索决策与缓存：[`search_engine.py`](../src/mika_chat_core/utils/search_engine.py)
- 图片处理与缓存：[`image_processor.py`](../src/mika_chat_core/utils/image_processor.py)、[`image_cache_core.py`](../src/mika_chat_core/utils/image_cache_core.py)
- 主动发言策略：[`matchers.py`](../src/mika_chat_core/matchers.py)
- 生命周期与健康检查：[`lifecycle.py`](../src/mika_chat_core/lifecycle.py)
- 配置与默认值：[`config.py`](../src/mika_chat_core/config.py)
- 文档：[`README.md`](../README.md)

## 2. 性能 / 稳定性改进

1) **搜索缓存参数化**
   - 新增配置：`mika_search_cache_ttl_seconds`、`mika_search_cache_max_size`。
   - 在启动时应用到搜索引擎全局缓存设置。
   - 影响文件：[`search_engine.py`](../src/mika_chat_core/utils/search_engine.py)、[`lifecycle.py`](../src/mika_chat_core/lifecycle.py)、[`config.py`](../src/mika_chat_core/config.py)。

2) **图片下载并发限制**
   - 新增配置：`mika_image_download_concurrency`。
   - 在图片处理器中引入异步信号量，限制并发下载。
   - 影响文件：[`image_processor.py`](../src/mika_chat_core/utils/image_processor.py)、[`config.py`](../src/mika_chat_core/config.py)。

3) **图片缓存容量限制**
   - 新增配置：`mika_image_cache_max_entries`（缓存条目上限）。
   - 在图片缓存核心中实现 LRU/先进先出淘汰。
   - 影响文件：[`image_cache_core.py`](../src/mika_chat_core/utils/image_cache_core.py)、[`image_cache_api.py`](../src/mika_chat_core/utils/image_cache_api.py)、[`lifecycle.py`](../src/mika_chat_core/lifecycle.py)、[`config.py`](../src/mika_chat_core/config.py)。

## 3. 可观测性 / 运维改进

1) **轻量指标统计**
   - 新增 `metrics.py`（内存指标）：请求数、工具调用数、搜索命中/失败、图片缓存命中、主动发言触发等。
   - 在关键路径递增计数并提供快照。
   - 影响文件：[`mika_api.py`](../src/mika_chat_core/mika_api.py)、[`mika_api_tools.py`](../src/mika_chat_core/mika_api_tools.py)、[`search_engine.py`](../src/mika_chat_core/utils/search_engine.py)、[`image_cache_core.py`](../src/mika_chat_core/utils/image_cache_core.py)、[`matchers.py`](../src/mika_chat_core/matchers.py)、新增 [`metrics.py`](../src/mika_chat_core/metrics.py)。

2) **新增 /metrics 端点**
   - 在 FastAPI 驱动下注册 `/metrics` 返回 JSON 指标快照。
   - 影响文件：[`lifecycle.py`](../src/mika_chat_core/lifecycle.py)。

## 4. 安全与合规改进

1) **工具调用白名单**
   - 新增配置：`mika_tool_allowlist`（默认包含现有工具）。
   - 在工具调用处理前校验，非允许工具返回安全提示。
   - 影响文件：[`mika_api_tools.py`](../src/mika_chat_core/mika_api_tools.py)、[`config.py`](../src/mika_chat_core/config.py)。

2) **工具结果长度上限**
   - 新增配置：`mika_tool_result_max_chars`，防止过长结果注入。
   - 影响文件：[`mika_api_tools.py`](../src/mika_chat_core/mika_api_tools.py)、[`config.py`](../src/mika_chat_core/config.py)。

## 5. 产品体验 / 功能改进

1) **图片关键词可配置**
   - 新增配置：`mika_image_keywords`（默认沿用现有内置关键词）。
   - 图片缓存使用该列表判断是否引用历史图片。
   - 影响文件：[`image_cache_core.py`](../src/mika_chat_core/utils/image_cache_core.py)、[`image_cache_api.py`](../src/mika_chat_core/utils/image_cache_api.py)、[`lifecycle.py`](../src/mika_chat_core/lifecycle.py)、[`config.py`](../src/mika_chat_core/config.py)。

2) **关键词触发冷却可配置**
   - 新增配置：`mika_proactive_keyword_cooldown`。
   - 替换硬编码最小冷却秒数，保持默认行为一致。
   - 影响文件：[`matchers.py`](../src/mika_chat_core/matchers.py)、[`config.py`](../src/mika_chat_core/config.py)。

## 6. 测试与回归

- 更新配置测试覆盖新增字段（默认值与验证）。
  - 影响文件：[`test_config.py`](../tests/test_config.py)。
- 视需要补充轻量测试以覆盖工具白名单/结果截断路径。
- 本轮回归：`pytest bot/tests/test_integration_flows.py -q` 与关键单元测试。

## 7. README 更新（仅新增功能）

- 新增条目：
  - `/metrics` 指标端点
  - 工具调用白名单与结果长度上限
  - 搜索缓存可配置
  - 图片缓存容量限制与关键词可配置
  - 图片下载并发限制

## 8. 实施顺序

1) 配置项扩展（[`config.py`](../src/mika_chat_core/config.py)）
2) 核心能力实现（缓存/并发/白名单/指标）
3) 生命周期挂载（[`lifecycle.py`](../src/mika_chat_core/lifecycle.py)）
4) 测试补齐（[`test_config.py`](../tests/test_config.py) 等）
5) Debug 与回归
6) README 更新（仅新增功能）
