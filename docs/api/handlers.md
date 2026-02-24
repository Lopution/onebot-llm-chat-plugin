# 消息处理器

本模块处理来自 QQ 的消息事件，并协调 Mika API 调用。

## 模块概述

消息处理模块提供以下功能函数：

- `handle_private()` - 处理私聊消息
- `handle_group()` - 处理群聊消息（@机器人时触发）
- `handle_reset()` - 处理清空记忆指令
- `send_forward_msg()` - 发送合并转发消息（用于长文本）

## API 参考

::: mika_chat_core.handlers
    options:
      show_source: true
      members_order: source
      show_root_heading: true
      show_if_no_docstring: false
