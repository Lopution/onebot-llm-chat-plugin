# Gemini API 客户端

本模块封装了 Google Gemini API 的调用逻辑。

## 模块概述

`GeminiClient` 类负责与 Google Gemini API 进行交互，支持：

- 文本对话生成
- 多模态输入（图片 + 文本）
- 工具调用（Function Calling）
- 上下文记忆管理

## API 参考

::: src.plugins.gemini_chat.gemini_api
    options:
      show_source: true
      members_order: source
      show_root_heading: true
      show_if_no_docstring: false
