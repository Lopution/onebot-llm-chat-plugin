# API 客户端

本模块通过 OpenAI 兼容格式 API 调用 LLM 模型。

## 模块概述

`MikaClient` 类负责通过 OpenAI 兼容格式与 Mika API 进行交互，支持：

- 文本对话生成
- 多模态输入（图片 + 文本）
- 工具调用（Function Calling）
- 上下文记忆管理

## API 参考

::: mika_chat_core.mika_api
    options:
      show_source: true
      members_order: source
      show_root_heading: true
      show_if_no_docstring: false
