<div align="center">

# Mika Bot 🌸

**A multimodal QQ chat bot plugin based on the OneBot protocol, using Gemini models through an OpenAI-compatible API**

[English](README_EN.md) | [中文](README.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-green.svg)](https://www.python.org/)
[![NoneBot2](https://img.shields.io/badge/NoneBot-2.0+-red.svg)](https://nonebot.dev/)
[![OneBot](https://img.shields.io/badge/OneBot-v11%20%2F%20v12-black.svg)](https://onebot.dev/)

[📖 Docs](docs/index.md) · [🐛 Report Issues](https://github.com/Lopution/onebot-llm-chat-plugin/issues) · [💡 Feature Requests](https://github.com/Lopution/onebot-llm-chat-plugin/issues)

</div>

---

## ✨ Highlights

<table>
<tr>
<td width="50%">

### 🤖 Intelligent Chat
Uses Gemini via an OpenAI-compatible API, with multi-turn context support

### 🔍 Web Search
Integrated Serper search for up-to-date information

### 💾 Context Memory
Persistent conversation storage based on SQLite

### 📝 Multi-turn Conversations
Maintains coherent context across continuous chats

</td>
<td width="50%">

### 🖼️ Image Understanding
Supports image input and multimodal understanding

### 💬 Proactive Replies
Semantic-matching-based proactive speaking strategy

### 👤 User Profiles
Automatically extracts and stores user profile signals

### 🔌 OneBot Protocol
OneBot v11/v12 support with best-effort auto-degradation

</td>
</tr>
</table>

---

## 🚀 Quick Start

### Minimal Setup

```bash
# 1. Clone and install
git clone https://github.com/Lopution/onebot-llm-chat-plugin.git
cd onebot-llm-chat-plugin
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure env
cp .env.example .env
# Edit .env and at least fill:
#   GEMINI_API_KEY=your-api-key
#   GEMINI_MASTER_ID=your-qq-number

# 3. Start
./start.sh
```

For Windows, run:

```powershell
.\start.ps1
```

### OneBot Connection (Reverse WebSocket)

After the bot starts, configure your OneBot implementation/client as a reverse WS client:

- **OneBot v11**: `ws://<HOST>:<PORT>/onebot/v11/ws`
- **OneBot v12**: `ws://<HOST>:<PORT>/onebot/v12/ws`

`<HOST>/<PORT>` comes from your `.env` (default: `0.0.0.0:8080`).

> 📌 Details and implementation differences: `docs/deploy/onebot.md`  
> 💡 Full deployment guide: [Installation & Run](#-installation--run)

---

## 📋 Prerequisites

### System Requirements

| Dependency | Version | Notes |
|------------|---------|-------|
| **Python** | 3.10+ | 3.11+ recommended |
| **Docker** | - | Used for NapCat QQ client |
| **OS** | Linux / Windows | Linux recommended; for Windows use WSL2 |

### Adapter & Runtime

| Component | Version | Notes |
|-----------|---------|-------|
| **OneBot Protocol** | v11 / v12 | Core communication protocol |
| **NoneBot2** | 2.0+ | Framework layer |
| **OneBot implementation/client** | Any | e.g. NapCat / go-cqhttp / others |

---

## 🔧 Installation & Run

### 1. Clone

```bash
git clone https://github.com/Lopution/onebot-llm-chat-plugin.git
cd onebot-llm-chat-plugin
```

### 2. Create a virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or .venv\Scripts\activate  # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

#### Config Reference

| Key | Description | Required | Default |
|-----|-------------|:--------:|---------|
| `GEMINI_API_KEY` | Gemini API key | ✅ | - |
| `GEMINI_BASE_URL` | API base URL (for proxy/gateway) | ❌ | - |
| `GEMINI_MODEL` | Primary model | ❌ | `gemini-3-pro-high` |
| `GEMINI_MASTER_ID` | Master QQ ID | ✅ | - |
| `GEMINI_GROUP_WHITELIST` | Group whitelist | ❌ | - |
| `GEMINI_OFFLINE_SYNC_ENABLED` | Offline sync (non-standard API, off by default) | ❌ | `false` |
| `GEMINI_LONG_MESSAGE_CHUNK_SIZE` | Chunk size when forward message is unavailable | ❌ | `800` |
| `SERPER_API_KEY` | Serper API key | ❌ | - |
| `MIKA_STRICT_STARTUP` | Strict startup mode (fail-fast on loader errors) | ❌ | `false` |

> 📖 Full config: [`docs/api/config.md`](docs/api/config.md)

### Minimal Custom Prompt Format

If you use a custom prompt file, keep at least this minimal structure:

```yaml
system_prompt: |
  You are a reliable and concise chat assistant.
```

If prompt structure is incomplete or invalid, the plugin falls back gracefully instead of crashing at startup/runtime.

### 5. Start NapCat (QQ client)

Make sure Docker is ready and start NapCat:

```bash
docker start napcat
```

### 6. Start the bot

**Option A: script (recommended)**

```bash
./start.sh
```

**Option B: direct**

```bash
python3 bot.py
```

---

## 🧰 WSL2 Long-running Deployment

If you deploy on Windows but want Bot + NapCat to run long-term in WSL2 (auto-start + auto-restart), see:

- 📖 [WSL2 deployment guide](docs/deploy/wsl2.md)
- 📁 systemd templates: [`deploy/wsl2/systemd/`](deploy/wsl2/systemd/)
- 📁 Windows scripts: [`deploy/wsl2/windows/`](deploy/wsl2/windows/)

---

## 📁 Project Structure

```
onebot-llm-chat-plugin/
├── bot.py                 # Bot entrypoint
├── start.sh               # Startup script (Linux/WSL)
├── .env.example           # Env template
├── requirements.txt       # Python dependencies
├── mkdocs.yml             # Docs config
│
├── src/plugins/
│   └── gemini_chat/       # Core plugin
│       ├── __init__.py
│       ├── config.py
│       ├── gemini_api.py
│       ├── handlers.py
│       ├── matchers.py
│       ├── lifecycle.py
│       ├── tools.py
│       ├── metrics.py
│       └── utils/
│
├── docs/                  # Documentation
└── tests/                 # Tests
```

---

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [Docs Home](docs/index.md) | Documentation entry |
| [API Client](docs/api/gemini_api.md) | API client usage |
| [Handlers](docs/api/handlers.md) | Message handling flow |
| [Search Engine](docs/api/search_engine.md) | Web search module |
| [Context Store](docs/api/context_store.md) | Context management |
| [Config](docs/api/config.md) | Full configuration |
| [OneBot Compatibility](docs/deploy/onebot.md) | v11/v12 compatibility notes |
| [Release Process](docs/release-process.md) | Tag/Release flow and rollback |

Build docs:

```bash
./scripts/build_docs.sh
# or
mkdocs serve
```

---

## 🧪 Testing

Run tests:

```bash
pytest tests/ -v
```

Run with coverage:

```bash
pytest tests/ -v --cov=src/plugins/gemini_chat --cov-report=html
```

---

## 🤝 Contribution & Security

- Contribution guide: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Security policy: [`SECURITY.md`](SECURITY.md)
- Third-party notices: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)

---

## 🙏 Acknowledgements

- [OneBot](https://onebot.dev/) - Unified bot communication protocol
- [NoneBot2](https://nonebot.dev/) - Async Python bot framework
- [Google Gemini](https://ai.google.dev/) - Multimodal model provider (through OpenAI-compatible APIs)
- [NapCat](https://github.com/NapNeko/NapCat) - QQ client implementation
- [AstrBot](https://github.com/Soulter/AstrBot) - Design inspiration for parts of strategy and implementation
- [Serper](https://serper.dev/) - Search API service

---

## 📄 License

This project is licensed under **GNU Affero General Public License v3.0 (AGPLv3)**.

In short:

- ✅ You can use, modify, and redistribute this software
- ✅ Commercial usage is allowed
- ⚠️ Modified versions must remain open-source under the same license
- ⚠️ If offered as a network service, source code must be provided

See [`LICENSE`](LICENSE) for details.

---

<div align="center">

**Made with ❤️ by Mika Bot Contributors**

[⬆ Back to top](#mika-bot-)

</div>
