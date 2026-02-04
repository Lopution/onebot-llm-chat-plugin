# Mika Bot API 文档

欢迎查阅 Mika Bot 的 API 文档！

## 项目简介

Mika Bot 是一个基于 NoneBot2 框架开发的 QQ 聊天机器人，集成了 Google Gemini API 进行智能对话。

### 主要特性

- 🤖 **智能对话**: 基于 Google Gemini 2.0 Flash 模型的自然语言对话
- 🔍 **联网搜索**: 集成 Serper API 搜索引擎，可获取实时信息
- 💾 **上下文记忆**: 基于 SQLite 的对话上下文持久化存储
- 📝 **多轮对话**: 支持连续多轮对话，保持上下文连贯
- 🖼️ **图片理解**: 支持图片输入和理解（多模态能力）

## 快速开始

### 安装依赖

```bash
pip install -e .
```

### 配置环境变量

复制 `.env.example` 为 `.env` 并填写配置：

```env
GEMINI_API_KEY=your_api_key_here
```

### 启动机器人

```bash
python bot.py
```

## 模块概览

| 模块 | 说明 |
|------|------|
| [`gemini_api`](api/gemini_api.md) | Gemini API 客户端封装 |
| [`handlers`](api/handlers.md) | 消息处理器 |
| [`search_engine`](api/search_engine.md) | Serper API 搜索引擎 (Google Search) |
| [`context_store`](api/context_store.md) | 对话上下文存储 |
| [`config`](api/config.md) | 配置管理 |

## 架构设计

```
src/plugins/gemini_chat/
├── __init__.py          # 插件入口
├── config.py            # 配置管理
├── gemini_api.py        # Gemini API 客户端
├── handlers.py          # 消息处理器
├── lifecycle.py         # 生命周期管理
├── matchers.py          # 消息匹配器
├── metrics.py           # 指标统计
├── tools.py             # 工具函数定义
└── utils/
    ├── context_store.py # 上下文存储
    ├── image_processor.py # 图片处理
    ├── prompt_loader.py # 提示词加载
    ├── search_engine.py # 搜索引擎
    └── user_profile.py  # 用户档案
```

## 许可证

本项目采用 MIT 许可证。
