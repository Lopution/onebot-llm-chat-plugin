# 小步拆分回归验证清单（兼容入口保持）

!!! warning "ARCHIVED / 已归档"
    本文是历史计划文档，不再保证与当前代码一致（尤其是模块拆分与导入路径）。
    
    - 项目总路线图：`docs/roadmap.md`
    - 长期架构方向：`docs/refactor_direction.md`

本次拆分仅新增内部模块并让 [`mika_api.py`](../src/mika_chat_core/mika_api.py:1) 作为兼容入口继续对外提供同名接口。

## ✅ 回归验证清单

1) **上下文读写与归档不变**
- 运行现有测试：[`tests/test_context_store.py`](../tests/test_context_store.py:1)

2) **空回复触发降级不变**
- 运行现有测试：[`tests/test_context_degradation.py`](../tests/test_context_degradation.py:1)

3) **工具调用链路不变**
- 触发包含工具调用的对话，确保仍能调用 [`tools.py`](../src/mika_chat_core/tools.py:1) 中的处理器

4) **搜索注入路径不变**
- 触发关键词或智能搜索，确认注入仍由 [`search_engine.py`](../src/mika_chat_core/utils/search_engine.py:1) 完成

5) **图片处理与多模态不变**
- 发送图片并请求识别，确认缓存/提取与原逻辑一致

## 新增内部模块（本轮）

- 回复清理：[`mika_api_sanitize.py`](../src/mika_chat_core/mika_api_sanitize.py:1)
- JSON 提取：[`mika_api_proactive.py`](../src/mika_chat_core/mika_api_proactive.py:1)
- 搜索前置与消息构建：[`mika_api_messages.py`](../src/mika_chat_core/mika_api_messages.py:1)
- 工具调用处理：[`mika_api_tools.py`](../src/mika_chat_core/mika_api_tools.py:1)
- 请求与错误映射：[`mika_api_transport.py`](../src/mika_chat_core/mika_api_transport.py:1)

## 兼容性说明

- 对外入口与导入路径保持：[`mika_api.py`](../src/mika_chat_core/mika_api.py:1)
- 对外接口与行为保持不变，仅内部委派到新模块
