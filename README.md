# Mika Bot 🌸

基于 NoneBot2 框架与 Google Gemini API 的智能 QQ 聊天机器人。

## ✨ 主要特性

- 🤖 **智能对话**：基于 Google Gemini 模型的自然语言对话
- 🔍 **联网搜索**：集成 Serper API 搜索引擎，可获取实时信息
- 💾 **上下文记忆**：基于 SQLite 的对话上下文持久化存储
- 📝 **多轮对话**：支持连续多轮对话，保持上下文连贯
- 🖼️ **图片理解**：支持图片输入和理解（多模态能力）
- 💬 **主动发言**：基于语义匹配的智能主动发言策略
- 👤 **用户档案**：自动抽取并记忆用户画像信息

## 📋 运行前置

### 系统要求

- **Python**: 3.10+
- **Docker**: 用于运行 NapCat QQ 客户端
- **操作系统**: Linux（推荐）/ Windows

### 适配器与运行环境

- **NoneBot2**: 2.0+
- **OneBot v11 适配器**: `nonebot-adapter-onebot`
- **QQ 客户端**: NapCat（Docker 部署）

## 🚀 安装与运行

### 1. 克隆项目

```bash
git clone <repository-url>
cd bot
```

### 2. 创建虚拟环境（推荐）

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或 .venv\Scripts\activate  # Windows
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置环境变量

复制 `.env.prod` 为 `.env` 并根据需要修改配置：

```bash
cp .env.prod .env
```

主要配置项：

| 配置项 | 说明 | 必填 |
|--------|------|------|
| `GEMINI_API_KEY` | Gemini API Key | ✅ |
| `GEMINI_BASE_URL` | API 基础地址（使用中转时填写） | ❌ |
| `GEMINI_MODEL` | 主模型名称 | ❌ |
| `GEMINI_MASTER_ID` | 主人 QQ 号 | ✅ |
| `GEMINI_GROUP_WHITELIST` | 群组白名单 | ❌ |
| `SERPER_API_KEY` | Serper 搜索 API Key | ❌ |

> 📖 完整配置说明请参阅 [`docs/api/config.md`](docs/api/config.md)

### 5. 启动 NapCat（QQ 客户端）

确保 Docker 已安装并运行 NapCat 容器：

```bash
docker start napcat
```

### 6. 启动机器人

**方式一：使用启动脚本（推荐）**

```bash
./start.sh
```

**方式二：直接运行**

```bash
python3 bot.py
```

## 🧰 WSL2 长期运行部署（systemd）

如果你希望在 Windows 本机部署，但 Bot 与 NapCat 都长期运行在 WSL2（并尽量做到“开机自动拉起 + 异常自动重启”），请看：

- `docs/deploy/wsl2.md`

相关模板与脚本位于：

- `deploy/wsl2/systemd/`
- `deploy/wsl2/windows/`

## 📁 项目结构

```
bot/
├── bot.py                 # 机器人入口
├── start.sh               # 启动脚本
├── .env.prod              # 生产环境配置示例
├── requirements.txt       # Python 依赖
├── mkdocs.yml             # 文档配置
│
├── src/plugins/
│   └── gemini_chat/       # 核心插件
│       ├── __init__.py    # 插件入口
│       ├── config.py      # 配置管理
│       ├── gemini_api.py  # Gemini API 客户端
│       ├── handlers.py    # 消息处理器
│       ├── matchers.py    # 消息匹配器
│       ├── lifecycle.py   # 生命周期管理
│       ├── tools.py       # 工具函数定义
│       ├── metrics.py     # 指标统计
│       └── utils/         # 工具模块
│           ├── context_store.py   # 上下文存储
│           ├── search_engine.py   # 搜索引擎
│           ├── image_processor.py # 图片处理
│           ├── user_profile.py    # 用户档案
│           └── ...
│
├── docs/                  # API 文档
├── tests/                 # 测试用例
├── data/                  # 运行时数据
├── logs/                  # 日志文件
└── models/                # 本地模型（语义匹配）
```

## 📖 文档

- [API 文档首页](docs/index.md)
- [Gemini 客户端](docs/api/gemini_api.md)
- [消息处理器](docs/api/handlers.md)
- [搜索引擎](docs/api/search_engine.md)
- [上下文存储](docs/api/context_store.md)
- [配置说明](docs/api/config.md)

构建文档站点：

```bash
./scripts/build_docs.sh
# 或
mkdocs serve
```

## 🧪 测试

运行测试：

```bash
pytest tests/ -v
```

## 📄 许可证

本项目采用 MIT 许可证。
