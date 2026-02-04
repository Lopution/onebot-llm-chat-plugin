#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAPCAT_DIR="${NAPCAT_DIR:-/root/napcat}"

cd "$NAPCAT_DIR"

WAIT_TIMEOUT_SECONDS="${DOCKER_WAIT_TIMEOUT_SECONDS:-180}"
if [[ -x "$SCRIPT_DIR/wait-docker.sh" ]]; then
  "$SCRIPT_DIR/wait-docker.sh" "$WAIT_TIMEOUT_SECONDS"
fi

# 自动把 OneBot WS Client 指向“容器访问宿主机”的网关（默认 bridge），减少手动改配置。
if [[ -x "$SCRIPT_DIR/napcat-configure-onebot-ws.sh" ]]; then
  "$SCRIPT_DIR/napcat-configure-onebot-ws.sh"
fi

# 如果名为 napcat 的容器已存在（例如通过 docker run 手动创建），优先直接启动它，
# 避免 docker compose 因“同名容器不属于该 compose 项目”而报冲突。
if docker inspect napcat >/dev/null 2>&1; then
  running="$(docker inspect -f '{{.State.Running}}' napcat 2>/dev/null || true)"
  if [[ "$running" == "true" ]]; then
    exit 0
  fi
  exec docker start napcat
fi

if docker compose version >/dev/null 2>&1; then
  exec docker compose up -d
fi

exec docker-compose up -d
