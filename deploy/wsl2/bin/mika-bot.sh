#!/usr/bin/env bash
set -euo pipefail

MIKA_BOT_DIR="${MIKA_BOT_DIR:-/root/onebot-llm-chat-plugin}"

cd "$MIKA_BOT_DIR"

PYTHON_BIN="python3"
if [[ -x "$MIKA_BOT_DIR/.venv/bin/python3" ]]; then
  PYTHON_BIN="$MIKA_BOT_DIR/.venv/bin/python3"
fi

exec "$PYTHON_BIN" bot.py
