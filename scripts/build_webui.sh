#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEBUI_DIR="$ROOT_DIR/webui"

if [[ ! -d "$WEBUI_DIR" ]]; then
  echo "[build_webui] webui directory not found: $WEBUI_DIR" >&2
  exit 1
fi

cd "$WEBUI_DIR"
if ! command -v npm >/dev/null 2>&1; then
  echo "[build_webui] npm not found. Please install Node.js first." >&2
  exit 1
fi

npm install
npm run build
echo "[build_webui] done"
