#!/usr/bin/env bash
# Open the release Tauri .app with FPA_ROOT pointed at this checkout.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Prefer a staged local release; fall back to the last Tauri build output.
if [ -d "$ROOT/releases/latest/Focal Point Aligner.app" ]; then
  APP="$ROOT/releases/latest/Focal Point Aligner.app"
else
  APP="$ROOT/src-tauri/target/release/bundle/macos/Focal Point Aligner.app"
fi

if [ ! -d "$APP" ]; then
  echo "App not found." >&2
  echo "Build a local release: ./scripts/release.sh" >&2
  echo "Or build only: ./build_macos.sh" >&2
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
