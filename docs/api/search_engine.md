# 搜索引擎

本模块封装了 Serper API 搜索引擎的调用逻辑。

## 模块概述

搜索模块提供网络搜索功能：

- 基于 Serper API 的文本搜索
- 结果解析和格式化
- 异步搜索支持
- 搜索结果缓存（减少重复请求）
- 可信来源优先排序

## 主要功能

| 函数 | 说明 |
|------|------|
| `serper_search()` | 执行 Google 搜索并返回格式化结果 |
| `classify_topic_for_search()` | 使用 LLM 智能分析查询是否需要搜索 |
| `should_search()` | 基于关键词快速判断是否需要搜索 |

## 使用示例

```python
from src.plugins.gemini_chat.utils.search_engine import serper_search, should_search

async def search_example():
    # 先用快速关键词检测
    if should_search("最新的 AI 新闻"):
        results = await serper_search("AI 新闻")
        print(results)
```

## API 参考

::: src.plugins.gemini_chat.utils.search_engine
    options:
      show_source: true
      members_order: source
      show_root_heading: true
      show_if_no_docstring: false
