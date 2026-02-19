# 配置管理

本模块定义了机器人的配置项。

## 模块概述

使用 Pydantic 进行配置验证和管理：

- 环境变量加载
- 配置验证
- 默认值设置
- 配置项类型检查

## 配置项

统一使用 `MIKA_*` 前缀。

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `MIKA_API_KEY` | str | OpenAI 兼容格式 API 密钥 | 必填 |
| `SERPER_API_KEY` | str | Serper 搜索 API 密钥 | 可选 |
| `MIKA_MODEL` | str | LLM 模型名称 | 必填 |
| `MIKA_FAST_MODEL` | str | 轻量任务默认模型（摘要/分类/抽取回退） | `gemini-2.5-flash-lite` |
| `MIKA_TASK_FILTER_MODEL` | str | 相关性过滤/判决专用模型（空=回退到 `MIKA_FAST_MODEL`） | `""` |
| `MIKA_TASK_SUMMARIZER_MODEL` | str | 上下文摘要专用模型（空=回退到 `MIKA_FAST_MODEL`） | `""` |
| `MIKA_TASK_MEMORY_MODEL` | str | 长期记忆抽取专用模型（空=回退到 `MIKA_FAST_MODEL`） | `""` |
| `MIKA_RELEVANCE_FILTER_ENABLED` | bool | 群聊相关性过滤开关（过滤无意义回复） | `false` |
| `MIKA_RELEVANCE_FILTER_MODEL` | str | 相关性过滤模型（空=回退到任务模型解析） | `""` |
| `MIKA_MESSAGE_SPLIT_ENABLED` | bool | 长回复自动分段发送开关 | `false` |
| `MIKA_MESSAGE_SPLIT_THRESHOLD` | int | 分段触发阈值（字符数） | `300` |
| `MIKA_PROMPT_FILE` | str | 角色提示词文件名（`prompts/` 目录下） | `system.yaml` |
| `MIKA_TOOL_PLUGINS` | list[str] | 工具插件模块列表（`module` 或 `module:Class`） | `[]` |
| `MIKA_MCP_SERVERS` | list[dict] | MCP 工具服务器配置（JSON 数组） | `[]` |

## Prompt V2（Breaking Change）

当前角色提示词采用 V2 schema，推荐文件为 `src/mika_chat_core/prompts/system.yaml`：

```yaml
name: "角色名"
character_prompt: |
  角色定义自由文本
dialogue_examples:
  - scenario: "示例"
    user: "用户输入"
    bot: "角色回复"
error_messages:
  default: "默认错误提示"
```

注意：
- 旧结构化字段 `role/personality/instructions/...` 不再保证兼容。
- 旧 `system_prompt` 字段不再作为正式入口。
- 缺失 `name` 或 `character_prompt` 时会回退到安全默认提示词，并输出告警日志。

## 使用示例

```python
from mika_chat_core.config import plugin_config

# 获取 API 密钥
api_key = plugin_config.mika_api_key
```

## API 参考

::: mika_chat_core.config
    options:
      show_source: true
      members_order: source
      show_root_heading: true
      show_if_no_docstring: false
