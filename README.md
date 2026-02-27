<div align="center">

# Mika Bot 🌸

**基于 OneBot 协议、使用 OpenAI 兼容格式 API 调用 LLM 模型的多模态智能 QQ 聊天机器人插件**

[中文](README.md) | [English](README_EN.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-green.svg)](https://www.python.org/)
[![NoneBot2](https://img.shields.io/badge/NoneBot-2.0+-red.svg)](https://nonebot.dev/)
[![OneBot](https://img.shields.io/badge/OneBot-v11%20%2F%20v12-black.svg)](https://onebot.dev/)

[📖 文档](docs/index.md) · [🐛 报告问题](https://github.com/Lopution/onebot-llm-chat-plugin/issues) · [💡 功能建议](https://github.com/Lopution/onebot-llm-chat-plugin/issues)

</div>

---

## ✨ 主要特性

<table>
<tr>
<td width="50%">

### 🤖 智能对话
通过 OpenAI 兼容格式 API 调用 LLM 模型，支持多轮上下文

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

### 新手 3 步（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/Lopution/onebot-llm-chat-plugin.git
cd onebot-llm-chat-plugin

# 2. 一键初始化（自动创建 .venv / 安装依赖 / 生成 .env / 补齐最小配置）
python3 scripts/bootstrap.py

# 3. 自检并启动
python3 scripts/doctor.py
python3 bot.py
```

Windows 用户可用同样流程：

```powershell
python scripts\bootstrap.py
python scripts\doctor.py
python bot.py
```

如果你更喜欢脚本启动方式，仍可使用 `./start.sh` 或 `.\start.ps1`。

### 标准 NoneBot 插件安装（迁移中）

本项目正在迁移为标准 NoneBot 插件包结构，推荐新项目优先使用标准模块名：

```bash
# 在 NoneBot 项目中（本地开发阶段）
pip install -e .
```

并在宿主中加载：

```python
nonebot.load_plugin("nonebot_plugin_mika_chat")
```

> 发布到 PyPI 后，可直接使用 `pip install nonebot-plugin-mika-chat` 或 `nb plugin install nonebot-plugin-mika-chat`。

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
| **Docker** | 可选 | 仅在 NapCat/Docker 部署时需要 |
| **操作系统** | Linux / Windows / WSL2 | 均可部署 |

### 适配器与运行环境

| 组件 | 版本 | 说明 |
|------|------|------|
| **OneBot 协议** | v11 / v12 | 核心通信协议 |
| **NoneBot2** | 2.0+ | 当前默认宿主（不是唯一方向） |
| **OneBot 实现/客户端** | 任意 | 例如 NapCat / go-cqhttp / 其它实现 |

---

## 🔧 安装与运行

### 选择部署方式

- **方案 A（推荐）**：Linux/Windows 本机 + 任意 OneBot 实现（无 Docker）
- **方案 B**：WSL2 + 任意 OneBot 实现（可选 Docker；使用 NapCat 时常见）

### 1. 克隆项目

```bash
git clone https://github.com/Lopution/onebot-llm-chat-plugin.git
cd onebot-llm-chat-plugin
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

你也可以直接运行交互式向导自动补齐最小配置：

```bash
python3 scripts/config_wizard.py
```

#### 配置项说明

统一使用三类前缀（单一入口）：
- `LLM_*`：LLM 连接与模型
- `SEARCH_*`：联网搜索（可选）
- `MIKA_*`：插件自身行为与功能开关

最小必填（只要这 2 项就能跑起来）：
- `LLM_API_KEY`（或 `LLM_API_KEY_LIST` 二选一）
- `MIKA_MASTER_ID`

常用项（不填则使用默认值）：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `LLM_PROVIDER` | LLM Provider | `openai_compat` |
| `LLM_BASE_URL` | OpenAI 兼容 API Base URL | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `LLM_MODEL` | 主模型 | `gemini-3-pro-high` |
| `LLM_FAST_MODEL` | 轻量模型（摘要/抽取等） | `gemini-2.5-flash-lite` |
| `SEARCH_PROVIDER` | 搜索 Provider（可选） | `serper` |
| `SEARCH_API_KEY` | 搜索 API Key（可选） | 空 |
| `MIKA_WEBUI_ENABLED` | WebUI（可选） | `false` |

⚠️ 破坏性升级：旧键（如 `MIKA_API_KEY` / `SERPER_API_KEY`）已切断，存在即启动失败。

> 📖 完整配置说明请参阅 [`docs/guide/configuration.md`](docs/guide/configuration.md)

### 自定义 Prompt（V2）

默认使用 `system.yaml`，格式为：

```yaml
name: "角色名"
character_prompt: |
  在这里写角色定义（自由文本）
dialogue_examples:
  - scenario: "示例"
    user: "用户输入"
    bot: "角色回复"
error_messages:
  default: "默认错误提示"
```

迁移说明（Breaking Change）：
- 旧结构化字段（`role/personality/instructions/...`）已下线，不再保证兼容。
- 旧 `system_prompt` 字段不再作为正式入口。
- 缺少 `name` 或 `character_prompt` 时会回退到安全默认提示词，并记录告警日志。

### 5. 启动你的 OneBot 实现（按你的部署方式）

- 如果你使用 NapCat + Docker：先启动 NapCat 容器
- 如果你使用其它 OneBot 实现：按该实现的文档启动即可

### 6. 启动机器人

**方式一：使用启动脚本（推荐）**

```bash
./start.sh
```

**方式二：直接运行**

```bash
python3 bot.py
```

启动前可先运行自检（推荐）：

```bash
python3 scripts/doctor.py
```

---

## 🧰 WSL2 部署（可选）

如果你希望在 Windows 环境下把 Bot 跑在 WSL2（更像 Linux 环境），请参阅：

- 📖 [WSL2 使用指南](docs/deploy/wsl2.md)

维护双仓（开源开发仓 + 本地部署仓）时，请参阅：
- 📖 [`docs/deploy/repo-sync.md`](docs/deploy/repo-sync.md)

---

## 📁 项目结构

```
onebot-llm-chat-plugin/
├── bot.py                 # 机器人入口
├── start.sh               # 启动脚本（Linux/WSL）
├── start.ps1              # 启动脚本（Windows）
├── .env.example           # 环境变量配置示例
├── pyproject.toml         # Python 依赖/打包配置
├── mkdocs.yml             # 文档配置
│
├── src/mika_chat_core/            # 中立核心模块（宿主无关）
├── src/nonebot_plugin_mika_chat/  # NoneBot 适配层（薄入口）
├── webui/                 # WebUI（前端）
│
├── docs/                  # 文档
└── tests/                 # 测试用例
```

---

## 📖 文档

| 文档 | 说明 |
|------|------|
| [文档首页](docs/index.md) | 文档入口 |
| [快速开始](docs/guide/quickstart.md) | 最短启动路径（推荐走 WebUI） |
| [WebUI 使用](docs/guide/webui.md) | 向导、基础/高级、effective snapshot |
| [排错](docs/guide/troubleshooting.md) | 空回复/上下文爆/图片/工具等常见问题 |
| [升级指南](docs/guide/upgrade.md) | 破坏性变更与迁移清单 |
| [发布流程](docs/release-process.md) | Tag/Release 发布与回滚 |

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
pytest tests/ -v --cov=src/mika_chat_core --cov-report=html
```

---

## 🤝 贡献与安全

- 贡献流程与规范：[`CONTRIBUTING.md`](CONTRIBUTING.md)
- 安全问题反馈：[`SECURITY.md`](SECURITY.md)
- 第三方参考说明：[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)

---

## 🙏 致谢

感谢以下项目和团队的贡献：

- [OneBot](https://onebot.dev/) - 统一的聊天机器人通信协议
- [NoneBot2](https://nonebot.dev/) - 优秀的 Python 异步机器人框架
- [Google AI](https://ai.google.dev/) - 强大的多模态 AI 模型（通过 OpenAI 兼容格式调用）
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
