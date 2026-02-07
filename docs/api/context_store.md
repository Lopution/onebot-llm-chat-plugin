# 上下文存储

本模块负责对话上下文的持久化存储。

## 模块概述

`SQLiteContextStore` 类提供对话历史的存储和检索功能：

- 基于 SQLite 的异步存储
- 按用户/群组管理上下文
- LRU 内存缓存优化
- 智能上下文压缩（保留关键信息）
- 用户身份信息提取

## 使用示例

```python
from mika_chat_core.utils.context_store import get_context_store

async def context_example():
    store = get_context_store()
    
    # 添加消息到上下文
    await store.add_message(
        user_id="123456",
        role="user",
        content="你好",
        group_id="789012"  # 可选，群聊时传入
    )
    
    # 获取上下文历史
    history = await store.get_context("123456", group_id="789012")
```

## API 参考

::: mika_chat_core.utils.context_store
    options:
      show_source: true
      members_order: source
      show_root_heading: true
      show_if_no_docstring: false
