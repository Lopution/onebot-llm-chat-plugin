<div align="center">

# Mika Bot 🌸

**基于 OneBot 协议、使用 OpenAI 兼容格式 API 调用 Gemini 模型的智能 QQ 聊天机器人**

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-green.svg)](https://www.python.org/)
[![NoneBot2](https://img.shields.io/badge/NoneBot-2.0+-red.svg)](https://nonebot.dev/)
[![OneBot](https://img.shields.io/badge/OneBot-v11%20%2F%20v12-black.svg)](https://onebot.dev/)

[📖 文档](docs/index.md) · [🐛 报告问题](../../issues) · [💡 功能建议](../../issues)

</div>

---

## ✨ 主要特性

<table>
<tr>
<td width="50%">

### 🤖 智能对话
通过 OpenAI 兼容格式 API 调用 Gemini 模型，支持多轮上下文

### 🔍 联网搜索
集成 Serper API 搜索引擎，可获取实时信息

### 💾 上下文记忆
基于 SQLite 的对话上下文持久化存储

### 📝 多轮对话
支持连续多轮对话，保持上下文连贯

</td>
<td width="50%">

### 🖼️ 图片理解
支持图片输入和理解（多模态能力）

### 💬 主动发言
基于语义匹配的智能主动发言策略

### 👤 用户档案
自动抽取并记忆用户画像信息

### 🔌 OneBot 协议
基于 OneBot v11/v12 协议（best-effort + 自动降级）

</td>
</tr>
</table>

---

## 🚀 快速开始

### 最小配置示例

```bash
# 1. 克隆并安装
git clone https://github.com/your-org/mika-bot.git
cd mika-bot/bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填写必要配置：
#   GEMINI_API_KEY=your-api-key
#   GEMINI_MASTER_ID=your-qq-number

# 3. 启动
./start.sh
```

Windows 用户可直接运行（首次会自动创建虚拟环境并安装依赖）：

```powershell
.\start.ps1
```

### OneBot 连接（反向 WebSocket）

Bot 启动后，需要在你的 OneBot 实现/客户端侧配置“反向 WebSocket（WS Client）”连接到 Bot：

- **OneBot v11**：`ws://<HOST>:<PORT>/onebot/v11/ws`
- **OneBot v12**：`ws://<HOST>:<PORT>/onebot/v12/ws`

其中 `<HOST>/<PORT>` 对应你的 `.env` 配置（默认 `0.0.0.0:8080`）。

> 📌 详细说明与不同实现的差异见：`docs/deploy/onebot.md`

> 💡 完整安装指南见下方 [安装与运行](#-安装与运行) 章节

---

## 📋 运行前置

### 系统要求

| 依赖项 | 版本要求 | 说明 |
|--------|----------|------|
| **Python** | 3.10+ | 推荐 3.11 或更高版本 |
| **Docker** | - | 用于运行 NapCat QQ 客户端 |
| **操作系统** | Linux / Windows | Linux 推荐；Windows 推荐使用 WSL2 |

### 适配器与运行环境

| 组件 | 版本 | 说明 |
|------|------|------|
| **OneBot 协议** | v11 / v12 | 核心通信协议 |
| **NoneBot2** | 2.0+ | 协议实现框架 |
| **OneBot 实现/客户端** | 任意 | 例如 NapCat / go-cqhttp / 其它实现 |

---

## 🔧 安装与运行

### 1. 克隆项目

```bash
git clone https://github.com/your-org/mika-bot.git
cd mika-bot/bot
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

复制 `.env.example` 为 `.env` 并根据需要修改配置：

```bash
cp .env.example .env
```

#### 配置项说明

| 配置项 | 说明 | 必填 | 默认值 |
|--------|------|:----:|--------|
| `GEMINI_API_KEY` | Gemini API Key | ✅ | - |
| `GEMINI_BASE_URL` | API 基础地址（使用中转时填写） | ❌ | - |
| `GEMINI_MODEL` | 主模型名称 | ❌ | `gemini-pro` |
| `GEMINI_MASTER_ID` | 主人 QQ 号 | ✅ | - |
| `GEMINI_GROUP_WHITELIST` | 群组白名单 | ❌ | - |
| `GEMINI_OFFLINE_SYNC_ENABLED` | 离线同步（非标准 API，默认关闭） | ❌ | `false` |
| `GEMINI_LONG_MESSAGE_CHUNK_SIZE` | 合并转发不可用时的分片大小 | ❌ | `500` |
| `SERPER_API_KEY` | Serper 搜索 API Key | ❌ | - |

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

---

## 🧰 WSL2 长期运行部署

如果你希望在 Windows 本机部署，但 Bot 与 NapCat 都长期运行在 WSL2（开机自动拉起 + 异常自动重启），请参阅：

- 📖 [WSL2 部署指南](docs/deploy/wsl2.md)
- 📁 systemd 模板：[`deploy/wsl2/systemd/`](deploy/wsl2/systemd/)
- 📁 Windows 脚本：[`deploy/wsl2/windows/`](deploy/wsl2/windows/)

---

## 📁 项目结构

```
bot/
├── bot.py                 # 机器人入口
├── start.sh               # 启动脚本
├── .env.example           # 环境变量配置示例
├── requirements.txt       # Python 依赖
├── mkdocs.yml             # 文档配置
│
├── src/plugins/
│   └── gemini_chat/       # 核心插件
│       ├── __init__.py    # 插件入口
│       ├── config.py      # 配置管理
│       ├── gemini_api.py  # OpenAI 兼容格式 API 客户端
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

---

## 📖 文档

| 文档 | 说明 |
|------|------|
| [API 文档首页](docs/index.md) | 文档入口 |
| [Gemini 客户端](docs/api/gemini_api.md) | API 客户端使用说明 |
| [消息处理器](docs/api/handlers.md) | 消息处理逻辑 |
| [搜索引擎](docs/api/search_engine.md) | 联网搜索功能 |
| [上下文存储](docs/api/context_store.md) | 上下文管理 |
| [配置说明](docs/api/config.md) | 完整配置参考 |
| [OneBot 兼容性](docs/deploy/onebot.md) | v11/v12 兼容性说明 |

### 构建文档站点

```bash
./scripts/build_docs.sh
# 或
mkdocs serve
```

---

## 🧪 测试

运行测试：

```bash
pytest tests/ -v
```

运行覆盖率测试：

```bash
pytest tests/ -v --cov=src/plugins/gemini_chat --cov-report=html
```

---

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出新功能建议！

### 如何贡献

1. **Fork** 本仓库
2. **创建** 特性分支 (`git checkout -b feature/AmazingFeature`)
3. **提交** 更改 (`git commit -m 'feat: add some amazing feature'`)
4. **推送** 到分支 (`git push origin feature/AmazingFeature`)
5. **创建** Pull Request

### 开发规范

- 遵循项目代码风格规范
- 使用中文编写注释和文档（技术术语可保留英文）
- 提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范
- 新功能需附带测试用例

### 提交信息格式

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

常用 type：
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `refactor`: 代码重构
- `test`: 测试相关
- `chore`: 构建/工具相关

---

## 🙏 致谢

感谢以下项目和团队的贡献：

- [OneBot](https://onebot.dev/) - 统一的聊天机器人通信协议
- [NoneBot2](https://nonebot.dev/) - 优秀的 Python 异步机器人框架
- [Google Gemini](https://ai.google.dev/) - 强大的多模态 AI 模型（通过 OpenAI 兼容格式调用）
- [NapCat](https://github.com/NapNeko/NapCat) - 稳定的 QQ 客户端实现
- [AstrBot](https://github.com/Soulter/AstrBot) - 部分思路和实现细节参考（AGPLv3）
- [Serper](https://serper.dev/) - 搜索 API 服务

特别感谢所有贡献者和使用者的支持！

---

## 📄 许可证

本项目采用 **GNU Affero General Public License v3.0 (AGPLv3)** 许可证。

这意味着：
- ✅ 您可以自由使用、修改和分发本软件
- ✅ 您可以将本软件用于商业目的
- ⚠️ 修改后的代码必须开源并使用相同许可证
- ⚠️ 通过网络提供服务也必须提供源代码

详见 [`LICENSE`](LICENSE) 文件。

---

<div align="center">

**Made with ❤️ by Mika Bot Contributors**

[⬆ 回到顶部](#mika-bot-)

</div>
