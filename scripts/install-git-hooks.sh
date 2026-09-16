#!/usr/bin/env bash
# Install local git hooks for this checkout (no remote CI).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_SRC="$ROOT/scripts/hooks/post-merge"
HOOK_DST="$ROOT/.git/hooks/post-merge"

if [ ! -d "$ROOT/.git" ]; then
  echo "Not a git checkout: $ROOT" >&2
  exit 1
fi

mkdir -p "$ROOT/.git/hooks"
cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST"
echo "Installed $HOOK_DST"
echo "Merges into the local 'release' branch will run ./scripts/release.sh"
