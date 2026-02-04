#!/usr/bin/env bash
set -euo pipefail

NAPCAT_DIR="${NAPCAT_DIR:-/root/napcat}"
BOT_PORT="${MIKA_BOT_PORT:-8080}"
BOT_PATH="${MIKA_BOT_ONEBOT_PATH:-/onebot/v11/ws}"

onebot_files=()
while IFS= read -r -d '' f; do
  onebot_files+=("$f")
done < <(find "$NAPCAT_DIR/data" -maxdepth 1 -type f -name 'onebot11_*.json' -print0 2>/dev/null || true)

if [[ ${#onebot_files[@]} -eq 0 ]]; then
  exit 0
fi

gateway="$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)"
if [[ -z "$gateway" ]]; then
  gateway="172.17.0.1"
fi

ws_url="ws://${gateway}:${BOT_PORT}${BOT_PATH}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found; skip updating OneBot websocketClients url" >&2
  exit 0
fi

python3 - "$ws_url" "${onebot_files[@]}" <<'PY'
import json
import sys
from pathlib import Path

ws_url = sys.argv[1]
files = [Path(p) for p in sys.argv[2:]]

DEFAULT_CLIENT = {
    "enable": True,
    "name": "Mika Bot",
    "url": ws_url,
    "reportSelfMessage": False,
    "messagePostFormat": "array",
    "token": "",
    "debug": False,
    "heartInterval": 30000,
    "reconnectInterval": 3000,
}


def ensure_ws_client(doc: dict) -> dict:
    network = doc.setdefault("network", {})
    ws_clients = network.setdefault("websocketClients", [])
    if not isinstance(ws_clients, list):
        ws_clients = []
        network["websocketClients"] = ws_clients

    # 优先更新名为 "Mika Bot" 的条目；否则更新第一个条目；否则插入默认条目
    target = None
    for item in ws_clients:
        if isinstance(item, dict) and item.get("name") == "Mika Bot":
            target = item
            break
    if target is None and ws_clients and isinstance(ws_clients[0], dict):
        target = ws_clients[0]

    if target is None:
        ws_clients.append(dict(DEFAULT_CLIENT))
        return doc

    target.setdefault("enable", True)
    target.setdefault("name", "Mika Bot")
    target["url"] = ws_url
    target.setdefault("reportSelfMessage", False)
    target.setdefault("messagePostFormat", "array")
    target.setdefault("token", "")
    target.setdefault("debug", False)
    target.setdefault("heartInterval", 30000)
    target.setdefault("reconnectInterval", 3000)
    return doc


for file in files:
    try:
        raw = file.read_text(encoding="utf-8")
        doc = json.loads(raw) if raw.strip() else {}
        if not isinstance(doc, dict):
            doc = {}
    except FileNotFoundError:
        continue
    except Exception:
        doc = {}

    ensure_ws_client(doc)
    file.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
