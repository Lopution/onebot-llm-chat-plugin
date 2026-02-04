#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

UNIT_SRC_DIR="$BOT_DIR/deploy/wsl2/systemd"
UNIT_DST_DIR="/etc/systemd/system"

install -m 0644 "$UNIT_SRC_DIR/napcat.service" "$UNIT_DST_DIR/napcat.service"
install -m 0644 "$UNIT_SRC_DIR/mika-bot.service" "$UNIT_DST_DIR/mika-bot.service"

chmod +x "$BOT_DIR/deploy/wsl2/bin/mika-bot.sh"
chmod +x "$BOT_DIR/deploy/wsl2/bin/napcat-up.sh"
chmod +x "$BOT_DIR/deploy/wsl2/bin/napcat-down.sh"
chmod +x "$BOT_DIR/deploy/wsl2/bin/wait-docker.sh"
chmod +x "$BOT_DIR/deploy/wsl2/bin/napcat-configure-onebot-ws.sh"

systemctl daemon-reload
systemctl enable --now napcat.service mika-bot.service

echo "Installed and started: napcat.service, mika-bot.service"
