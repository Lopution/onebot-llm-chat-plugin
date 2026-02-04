# 配置管理

本模块定义了机器人的配置项。

## 模块概述

使用 Pydantic 进行配置验证和管理：

- 环境变量加载
- 配置验证
- 默认值设置
- 配置项类型检查

## 配置项

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `GEMINI_API_KEY` | str | Google Gemini API 密钥 | 必填 |
| `SERPER_API_KEY` | str | Serper 搜索 API 密钥 | 可选 |
| `GEMINI_MODEL` | str | Gemini 模型名称 | `gemini-2.0-flash-exp` |

## 使用示例

```python
from src.plugins.gemini_chat.config import plugin_config

# 获取 API 密钥
api_key = plugin_config.gemini_api_key
```

## API 参考

::: src.plugins.gemini_chat.config
    options:
      show_source: true
      members_order: source
      show_root_heading: true
      show_if_no_docstring: false
