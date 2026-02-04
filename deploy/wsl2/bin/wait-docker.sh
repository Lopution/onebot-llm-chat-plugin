#!/usr/bin/env bash
set -euo pipefail

timeout_seconds="${1:-180}"
deadline=$(( $(date +%s) + timeout_seconds ))

while true; do
  if docker info >/dev/null 2>&1; then
    exit 0
  fi

  if [[ $(date +%s) -ge $deadline ]]; then
    echo "docker not ready after ${timeout_seconds}s" >&2
    exit 1
  fi

  sleep 2
done

