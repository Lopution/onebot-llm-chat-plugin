# Quickstart

## Requirements

- Python 3.10+
- A OneBot implementation/client that supports **reverse WebSocket (WS Client)**

## 3-step setup (recommended)

1. Clone and bootstrap

```bash
git clone https://github.com/Lopution/onebot-llm-chat-plugin.git
cd onebot-llm-chat-plugin
python3 scripts/bootstrap.py
```

2. Fill the minimum required env values

Copy `.env.example` to `.env`, then at least set:

```env
LLM_API_KEY="YOUR_API_KEY"
MIKA_MASTER_ID=123456789
```

Notes:
- `LLM_API_KEY` and `LLM_API_KEY_LIST` are alternatives (choose one).
- Legacy keys like `MIKA_API_KEY` / `SERPER_API_KEY` are removed; if present, startup will fail fast.

3. Doctor check then start

```bash
python3 scripts/doctor.py
python3 bot.py
```

## OneBot reverse WS endpoints

- OneBot v11: `ws://<HOST>:<PORT>/onebot/v11/ws`
- OneBot v12: `ws://<HOST>:<PORT>/onebot/v12/ws`

See: [`../../deploy/onebot.md`](../../deploy/onebot.md)

