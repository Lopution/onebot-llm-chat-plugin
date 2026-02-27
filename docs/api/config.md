# 配置管理

本页是 **API 参考**。用户侧配置项说明请以 `docs/guide/configuration.md` 为准（后续由代码 schema 自动生成，避免配置表过时）。

## 模块概述

使用 Pydantic 进行配置验证和管理：

- 环境变量加载
- 配置验证
- 默认值设置
- 配置项类型检查

## 配置入口（环境变量）

当前配置使用三类前缀作为单一入口：

- `LLM_*`：LLM Provider/Base URL/API Key/模型
- `SEARCH_*`：联网搜索（可选）
- `MIKA_*`：插件功能与行为开关

⚠️ 旧键（如 `MIKA_API_KEY` / `SERPER_API_KEY`）已移除，存在即启动失败。迁移见：`docs/guide/upgrade.md`。

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

## API 参考

::: mika_chat_core.config
    options:
      show_source: true
      members_order: source
      show_root_heading: true
      show_if_no_docstring: false
