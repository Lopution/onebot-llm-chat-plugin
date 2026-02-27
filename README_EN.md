<div align="center">

# Mika Bot 🌸

**A multimodal QQ chat bot plugin based on the OneBot protocol, using LLM models through an OpenAI-compatible API**

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
Uses an LLM via an OpenAI-compatible API, with multi-turn context support

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

### Beginner 3-Step Setup (Recommended)

```bash
# 1. Clone
git clone https://github.com/Lopution/onebot-llm-chat-plugin.git
cd onebot-llm-chat-plugin

# 2. One-click bootstrap
# (create .venv, install deps, generate .env, and fill minimum required config)
python3 scripts/bootstrap.py

# 3. Doctor check then start
python3 scripts/doctor.py
python3 bot.py
```

For Windows, use the same flow:

```powershell
python scripts\bootstrap.py
python scripts\doctor.py
python bot.py
```

If you prefer script launch, `./start.sh` and `.\start.ps1` are still available.

### Standard NoneBot Plugin Installation (Migration in Progress)

This repository is being migrated to a standard NoneBot plugin package layout.
For new projects, prefer loading the standard module name:

```bash
# Inside your NoneBot project (local development stage)
pip install -e .
```

Then load it in your host app:

```python
nonebot.load_plugin("nonebot_plugin_mika_chat")
```

> After PyPI release, you can use `pip install nonebot-plugin-mika-chat` or `nb plugin install nonebot-plugin-mika-chat`.

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
| **Docker** | Optional | Needed only for NapCat/Docker deployment |
| **OS** | Linux / Windows / WSL2 | All supported |

### Adapter & Runtime

| Component | Version | Notes |
|-----------|---------|-------|
| **OneBot Protocol** | v11 / v12 | Core communication protocol |
| **NoneBot2** | 2.0+ | Current default host (not the only direction) |
| **OneBot implementation/client** | Any | e.g. NapCat / go-cqhttp / others |

---

## 🔧 Installation & Run

### Choose Deployment Mode

- **Mode A (recommended)**: Linux/Windows host + any OneBot implementation (no Docker)
- **Mode B**: WSL2 + any OneBot implementation (Docker optional; common with NapCat)

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

You can also run the interactive wizard to fill the minimum config automatically:

```bash
python3 scripts/config_wizard.py
```

#### Config Reference

There are 3 env namespaces (single source of truth):
- `LLM_*`: LLM connection and models
- `SEARCH_*`: Web search (optional)
- `MIKA_*`: Plugin behaviors and feature toggles

Minimum required (only these 2 to get started):
- `LLM_API_KEY` (or `LLM_API_KEY_LIST`)
- `MIKA_MASTER_ID`

Common options (defaults will be used if omitted):

| Key | Description | Default |
|-----|-------------|---------|
| `LLM_PROVIDER` | LLM provider | `openai_compat` |
| `LLM_BASE_URL` | OpenAI-compatible API base URL | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `LLM_MODEL` | Primary model | `gemini-3-pro-high` |
| `LLM_FAST_MODEL` | Fast/light model (summary/extraction) | `gemini-2.5-flash-lite` |
| `SEARCH_PROVIDER` | Search provider (optional) | `serper` |
| `SEARCH_API_KEY` | Search API key (optional) | empty |
| `MIKA_WEBUI_ENABLED` | WebUI (optional) | `false` |

⚠️ Breaking change: legacy keys (e.g. `MIKA_API_KEY` / `SERPER_API_KEY`) are removed. If present, startup will fail fast.

> 📖 Full config: [`docs/guide/configuration.md`](docs/guide/configuration.md)

### Custom Prompt (V2)

Default prompt file is `system.yaml`:

```yaml
name: "Character Name"
character_prompt: |
  Put your role/persona definition here (free text).
dialogue_examples:
  - scenario: "Example"
    user: "User input"
    bot: "Character reply"
error_messages:
  default: "Default error message"
```

Migration note (Breaking Change):
- Legacy structured keys (`role/personality/instructions/...`) are removed from supported schema.
- Legacy `system_prompt` is no longer a formal entry field.
- If `name` or `character_prompt` is missing, loader falls back to a safe default prompt and emits warning logs.

### 5. Start your OneBot implementation

- If you use NapCat + Docker, start NapCat container first
- If you use another OneBot implementation, start it following its own docs

### 6. Start the bot

**Option A: script (recommended)**

```bash
./start.sh
```

**Option B: direct**

```bash
python3 bot.py
```

Recommended before startup:

```bash
python3 scripts/doctor.py
```

---

## 🧰 WSL2 (Optional)

If you run the Bot inside WSL2 on Windows, see:

- 📖 [WSL2 guide](docs/deploy/wsl2.md)

For dual-repo maintenance (open-source dev repo + local deployment repo), see:
- 📖 [`docs/deploy/repo-sync.md`](docs/deploy/repo-sync.md)

---

## 📁 Project Structure

```
onebot-llm-chat-plugin/
├── bot.py                 # Bot entrypoint
├── start.sh               # Startup script (Linux/WSL)
├── start.ps1              # Startup script (Windows)
├── .env.example           # Env template
├── pyproject.toml         # Python deps / packaging config
├── mkdocs.yml             # Docs config
│
├── src/mika_chat_core/            # Host-agnostic core module
├── src/nonebot_plugin_mika_chat/  # NoneBot adapter layer (thin entry)
├── webui/                 # WebUI (frontend)
│
├── docs/                  # Documentation
└── tests/                 # Tests
```

---

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [Docs Home](docs/index.md) | Documentation entry |
| [Quickstart](docs/guide/quickstart.md) | Shortest path (WebUI recommended) |
| [WebUI](docs/guide/webui.md) | Wizard, basic/advanced, effective snapshot |
| [Troubleshooting](docs/guide/troubleshooting.md) | Empty replies/context overflow/media/tools |
| [Upgrade](docs/guide/upgrade.md) | Breaking changes and migration checklist |
| [OneBot Compatibility](docs/deploy/onebot.md) | v11/v12 compatibility notes |
| [Cross-platform Acceptance Matrix](docs/deploy/acceptance-matrix.md) | Linux/Windows/WSL2 validation checklist |
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
pytest tests/ -v --cov=src/mika_chat_core --cov-report=html
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
- [Google AI](https://ai.google.dev/) - Multimodal model provider (through OpenAI-compatible APIs)
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
