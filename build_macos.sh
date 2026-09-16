#!/usr/bin/env bash
# Build the unsigned Tauri macOS .app (React UI + Python FastAPI via project ./venv).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -x "./venv/bin/python" ]; then
  echo "Create ./venv first:"
  echo "  python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [ ! -d web/node_modules ]; then
  npm --prefix web install
fi
if [ ! -d node_modules ]; then
  npm install
fi

# shellcheck disable=SC1090
source "$HOME/.cargo/env" 2>/dev/null || true
npm run build

APP="$ROOT/src-tauri/target/release/bundle/macos/Focal Point Aligner.app"
echo ""
echo "App bundle: $APP"
echo "Unsigned: first open via Finder → right-click → Open."
echo "Needs this checkout + ./venv (or set FPA_ROOT / FPA_PYTHON)."
echo "Quick launch: ./scripts/open-app.sh"
