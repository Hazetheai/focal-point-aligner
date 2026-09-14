#!/usr/bin/env bash
# Build the Tauri macOS .app (React UI + Python FastAPI sidecar at runtime via venv).
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -x "./venv/bin/python" ]; then
  echo "Create ./venv first: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [ ! -d web/node_modules ]; then
  npm --prefix web install
fi
if [ ! -d node_modules ]; then
  npm install
fi

source "$HOME/.cargo/env" 2>/dev/null || true
npm run build

echo ""
echo "App bundle: src-tauri/target/release/bundle/macos/Focal Point Aligner.app"
echo "The app expects this project (and ./venv) next to it for the Python API, or set FPA_ROOT / FPA_PYTHON."
