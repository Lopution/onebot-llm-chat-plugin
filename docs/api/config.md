# 配置管理（单一入口）

当前版本采用 **一套配置模型**（`mika_chat_core.config.Config`）：

- 宿主适配层（当前是 `nonebot_plugin_mika_chat`）在启动时加载配置
- 然后注入 `mika_chat_core.runtime`
- 核心模块统一通过 runtime 读取配置，不直接依赖宿主框架

## 设计原则

- 单一配置源：所有功能配置都在 `Config` 内定义与校验。
- 兼容旧键名：保留 `GEMINI_*` / `SERPER_*`，自动映射到新的 provider 配置。
- 低风险迁移：旧部署不改 `.env` 也能继续运行。
- 兼容桥接受控：兼容壳仅允许存在于边界层（`runtime/deps`），核心业务不新增宿主耦合。

## LLM Provider 配置

推荐使用新字段：

| 配置项 | 说明 |
|---|---|
| `MIKA_LLM_PROVIDER` | `openai_compat` / `anthropic` / `google_genai` |
| `MIKA_LLM_BASE_URL` | API 基地址（`openai_compat` 常用） |
| `MIKA_LLM_API_KEY` | 主 key |
| `MIKA_LLM_API_KEY_LIST` | 轮换 key 列表 |
| `MIKA_LLM_MODEL` | 主模型 |
| `MIKA_LLM_FAST_MODEL` | 快速模型 |
| `MIKA_LLM_EXTRA_HEADERS_JSON` | 额外请求头（JSON 字符串） |

兼容逻辑（自动）：

- 若未设置 `MIKA_LLM_*`，会回退读取旧键 `GEMINI_*`。
- 默认兼容模式是 `openai_compat`，可接 OpenAI / OpenRouter / NewAPI / 多数兼容网关。

### LLM 能力矩阵（当前实现）

| Provider | 工具调用 | 图片输入 | `response_format=json_object` |
|---|---|---|---|
| `openai_compat` | ✅ | ✅ | ✅ |
| `anthropic` | ✅（映射到 `tool_use/tool_result`） | ✅（data URL 映射） | ❌（自动走文本 JSON 提取） |
| `google_genai` | ✅（映射到 function call） | ✅（映射到 `inline_data`） | ❌（自动走文本 JSON 提取） |

说明：

- 当 provider 不支持 `response_format` 时，分类/判决/抽取链路不会发送该字段，避免无效 4xx。
- `embedding/rerank` 类模型会自动关闭工具与图片能力，按纯文本路径处理。

## Search Provider 配置

| 配置项 | 说明 |
|---|---|
| `MIKA_SEARCH_PROVIDER` | `serper` / `tavily` |
| `MIKA_SEARCH_API_KEY` | 搜索服务 key |
| `MIKA_SEARCH_EXTRA_HEADERS_JSON` | 额外请求头（JSON 字符串） |

兼容逻辑（自动）：

- 若未设置 `MIKA_SEARCH_API_KEY`，会回退到 `SERPER_API_KEY`。

### Search 能力矩阵（当前实现）

| Provider | 说明 |
|---|---|
| `serper` | 默认 provider，支持结果过滤、可信源排序、注入文本生成 |
| `tavily` | 可通过 `MIKA_SEARCH_PROVIDER=tavily` 切换，沿用同一编排/缓存/去重策略 |

## Core Runtime 配置（Stage C）

| 配置项 | 说明 |
|---|---|
| `MIKA_CORE_RUNTIME_MODE` | `embedded` / `remote` |
| `MIKA_CORE_REMOTE_BASE_URL` | `remote` 模式下的 Core Service 地址 |
| `MIKA_CORE_REMOTE_TIMEOUT_SECONDS` | 远程请求超时（秒） |
| `MIKA_CORE_SERVICE_TOKEN` | 可选，`/v1/events` 鉴权 token |

说明：

- `embedded`：适配层直接调用本进程 Core。
- `remote`：适配层通过 HTTP 调用 `POST /v1/events`，返回 `Action[]` 后再执行。
- 当前版本会在 NoneBot 应用内暴露 `POST /v1/events`，可用于同机 remote smoke test 或跨语言 PoC。

## 兼容桥接与弃用策略

当前仍保留以下兼容壳（用于平滑迁移，不是长期目标）：

- `mika_chat_core.deps`：历史调用点兼容桥，依赖 runtime hook 注入。
- `runtime.get_config()` 最小配置兜底：保障测试/早期导入场景可运行。

执行约束：

- 新能力必须走 `Config + runtime` 主路径，不新增隐式回退入口。
- 新宿主适配仅落在 adapter 层；核心层保持 host-agnostic。

## 代码中读取配置

核心模块应通过 runtime 读取：

```python
from mika_chat_core.runtime import get_config

config = get_config()
llm_cfg = config.get_llm_config()
search_cfg = config.get_search_config()
```

适配层在启动时注入：

```python
from mika_chat_core.runtime import set_config

set_config(plugin_config)
```

## API 参考

::: mika_chat_core.config
    options:
      show_source: true
      members_order: source
      show_root_heading: true
      show_if_no_docstring: false
