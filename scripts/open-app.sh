#!/usr/bin/env bash
# Open the release Tauri .app with FPA_ROOT pointed at this checkout.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/src-tauri/target/release/bundle/macos/Focal Point Aligner.app"

if [ ! -d "$APP" ]; then
  echo "App not found: $APP" >&2
  echo "Build first: ./build_macos.sh" >&2
  exit 1
fi

if [ ! -x "$ROOT/venv/bin/python" ]; then
  echo "Missing $ROOT/venv/bin/python — create the venv and install requirements.txt" >&2
  exit 1
fi

export FPA_ROOT="$ROOT"
echo "Opening $APP"
echo "FPA_ROOT=$FPA_ROOT"
open "$APP"
