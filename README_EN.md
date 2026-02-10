<div align="center">

# Mika Bot 🌸

**A multimodal QQ chat bot plugin based on the OneBot protocol, using Gemini models through an OpenAI-compatible API**

[English](README_EN.md) | [中文](README.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-green.svg)](https://www.python.org/)
[![NoneBot2](https://img.shields.io/badge/NoneBot-2.0+-red.svg)](https://nonebot.dev/)
[![OneBot](https://img.shields.io/badge/OneBot-v11%20%2F%20v12-black.svg)](https://onebot.dev/)

[📖 Docs](docs/index.md) · [🐛 Report Issues](https://github.com/Lopution/mika-chat-core/issues) · [💡 Feature Requests](https://github.com/Lopution/mika-chat-core/issues)

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

### Beginner 3-Step Setup (Recommended)

```bash
# 1. Clone
git clone https://github.com/Lopution/mika-chat-core.git
cd mika-chat-core

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
git clone https://github.com/Lopution/mika-chat-core.git
cd mika-chat-core
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

> Note: from this version, prefer `MIKA_LLM_*` / `MIKA_SEARCH_*` as canonical keys for LLM/Search.  
> Legacy `GEMINI_*` / `SERPER_API_KEY` are still supported for compatibility.

| Key | Description | Required | Default |
|-----|-------------|:--------:|---------|
| `MIKA_LLM_API_KEY` | LLM API key (compatible with legacy `GEMINI_API_KEY`) | ✅ | - |
| `MIKA_LLM_BASE_URL` | LLM API base URL (proxy/gateway use) | ❌ | - |
| `MIKA_LLM_PROVIDER` | LLM provider (`openai_compat` / `anthropic` / `google_genai`) | ❌ | `openai_compat` |
| `MIKA_LLM_MODEL` | Primary model | ❌ | `gemini-3-pro-high` |
| `MIKA_LLM_FAST_MODEL` | Fast model | ❌ | `gemini-2.5-flash-lite` |
| `MIKA_MASTER_ID` | Master QQ ID (compatible with legacy `GEMINI_MASTER_ID`) | ✅ | - |
| `MIKA_GROUP_WHITELIST` | Group whitelist (compatible with legacy `GEMINI_GROUP_WHITELIST`) | ❌ | - |
| `GEMINI_OFFLINE_SYNC_ENABLED` | Offline sync (non-standard API, off by default) | ❌ | `false` |
| `GEMINI_CONTEXT_MODE` | Context mode (`legacy`/`structured`) | ❌ | `structured` |
| `GEMINI_CONTEXT_MAX_TURNS` | Max context turns (applied before raw message count trim) | ❌ | `30` |
| `GEMINI_CONTEXT_MAX_TOKENS_SOFT` | Soft token threshold for context trimming (estimated) | ❌ | `12000` |
| `GEMINI_CONTEXT_SUMMARY_ENABLED` | Enable summary compression (disabled by default) | ❌ | `false` |
| `GEMINI_MULTIMODAL_STRICT` | Strict multimodal sanitation when capability is missing | ❌ | `true` |
| `GEMINI_QUOTE_IMAGE_CAPTION_ENABLED` | Add caption hint for quoted images (best-effort) | ❌ | `true` |
| `GEMINI_QUOTE_IMAGE_CAPTION_PROMPT` | Quote-image hint template (supports `{count}`) | ❌ | `[引用图片共{count}张]` |
| `GEMINI_QUOTE_IMAGE_CAPTION_TIMEOUT_SECONDS` | Quote message parsing timeout (seconds) | ❌ | `3.0` |
| `GEMINI_LONG_REPLY_IMAGE_FALLBACK_ENABLED` | Enable rendered-image fallback on send failure | ❌ | `true` |
| `GEMINI_LONG_REPLY_IMAGE_MAX_CHARS` | Max chars for rendered long-reply image | ❌ | `12000` |
| `GEMINI_LONG_REPLY_IMAGE_MAX_WIDTH` | Rendered image width (px) | ❌ | `960` |
| `GEMINI_LONG_REPLY_IMAGE_FONT_SIZE` | Rendered image font size | ❌ | `24` |
| `GEMINI_LONG_MESSAGE_CHUNK_SIZE` | Compatibility-only (not used in main fallback chain) | ❌ | `800` |
| `GEMINI_EMPTY_REPLY_LOCAL_RETRIES` | Transport-level local retries on empty replies (without replaying full chain) | ❌ | `1` |
| `GEMINI_EMPTY_REPLY_LOCAL_RETRY_DELAY_SECONDS` | Delay between local empty-reply retries (seconds) | ❌ | `0.4` |
| `GEMINI_TRANSPORT_TIMEOUT_RETRIES` | Transport-level local retries for timeout only | ❌ | `1` |
| `GEMINI_TRANSPORT_TIMEOUT_RETRY_DELAY_SECONDS` | Delay between timeout retries (seconds) | ❌ | `0.6` |
| `GEMINI_EMPTY_REPLY_CONTEXT_DEGRADE_ENABLED` | Enable business-level context degradation on empty replies | ❌ | `false` |
| `GEMINI_EMPTY_REPLY_CONTEXT_DEGRADE_MAX_LEVEL` | Max degradation level for business-level context retries | ❌ | `2` |
| `GEMINI_METRICS_PROMETHEUS_ENABLED` | Enable Prometheus text output on `/metrics` | ❌ | `true` |
| `GEMINI_HEALTH_CHECK_API_PROBE_ENABLED` | Enable active API probe in `/health` | ❌ | `false` |
| `GEMINI_HEALTH_CHECK_API_PROBE_TIMEOUT_SECONDS` | API health probe timeout (seconds) | ❌ | `3.0` |
| `GEMINI_HEALTH_CHECK_API_PROBE_TTL_SECONDS` | API health probe cache TTL (seconds) | ❌ | `30` |
| `GEMINI_CONTEXT_TRACE_ENABLED` | Enable context-build trace logs | ❌ | `false` |
| `GEMINI_CONTEXT_TRACE_SAMPLE_RATE` | Context trace sampling ratio (0~1) | ❌ | `1.0` |
| `GEMINI_ACTIVE_REPLY_LTM_ENABLED` | Global gate for proactive LTM-like reply | ❌ | `true` |
| `GEMINI_ACTIVE_REPLY_PROBABILITY` | Final probability gate for proactive reply (0~1) | ❌ | `1.0` |
| `GEMINI_ACTIVE_REPLY_WHITELIST` | Group whitelist for proactive reply (empty = no extra limit) | ❌ | `[]` |
| `MIKA_SEARCH_API_KEY` | Search API key (compatible with `SERPER_API_KEY`) | ❌ | - |
| `MIKA_STRICT_STARTUP` | Strict startup mode (fail-fast on loader errors) | ❌ | `false` |

> 📖 Full config: [`docs/api/config.md`](docs/api/config.md)

### Minimal Custom Prompt Format

If you use a custom prompt file, keep at least this minimal structure:

```yaml
system_prompt: |
  You are a reliable and concise chat assistant.
```

If prompt structure is incomplete or invalid, the plugin falls back gracefully instead of crashing at startup/runtime.

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
mika-chat-core/
├── bot.py                 # Bot entrypoint
├── start.sh               # Startup script (Linux/WSL)
├── .env.example           # Env template
├── requirements.txt       # Python dependencies
├── mkdocs.yml             # Docs config
│
├── src/mika_chat_core/            # Host-agnostic core module
│       ├── config.py
│       ├── gemini_api.py
│       ├── handlers.py
│       ├── matchers.py
│       ├── lifecycle.py
│       ├── tools.py
│       ├── metrics.py
│       └── utils/
│
├── src/nonebot_plugin_mika_chat/  # NoneBot adapter layer (thin entry)
│       └── __init__.py
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
