#!/usr/bin/env bash
set -euo pipefail

NAPCAT_DIR="${NAPCAT_DIR:-/root/napcat}"

if ! docker info >/dev/null 2>&1; then
  exit 0
fi

# 如果名为 napcat 的容器存在（可能非 compose 创建），优先直接停掉它。
if docker inspect napcat >/dev/null 2>&1; then
  running="$(docker inspect -f '{{.State.Running}}' napcat 2>/dev/null || true)"
  if [[ "$running" == "true" ]]; then
    exec docker stop napcat
  fi
  exit 0
fi

cd "$NAPCAT_DIR"

if docker compose version >/dev/null 2>&1; then
  exec docker compose down
fi

exec docker-compose down
