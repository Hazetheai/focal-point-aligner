#!/usr/bin/env bash
# Local unsigned macOS release: build Tauri .app into ./releases/ (never pushes).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BUMP=""
SKIP_BUILD=0
SKIP_TAG=0
while [ $# -gt 0 ]; do
  case "$1" in
    --bump)
      BUMP="${2:-}"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    --skip-tag)
      SKIP_TAG=1
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Usage: ./scripts/release.sh [--bump patch|minor|major] [--skip-build] [--skip-tag]

Builds the unsigned Tauri .app and copies it to:
  releases/vX.Y.Z/Focal Point Aligner.app
  releases/latest -> vX.Y.Z

Creates a local git tag vX.Y.Z (does not push).
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

read_version() {
  python3 - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("package.json").read_text())["version"])
PY
}

set_version() {
  local ver="$1"
  python3 - "$ver" <<'PY'
import json, sys
from pathlib import Path
ver = sys.argv[1]
for rel in ("package.json", "src-tauri/tauri.conf.json"):
    path = Path(rel)
    data = json.loads(path.read_text())
    data["version"] = ver
    path.write_text(json.dumps(data, indent=2) + "\n")
# Keep Cargo.toml in sync when present
cargo = Path("src-tauri/Cargo.toml")
if cargo.is_file():
    lines = []
    in_pkg = False
    for line in cargo.read_text().splitlines():
        if line.strip() == "[package]":
            in_pkg = True
        elif line.startswith("[") and in_pkg:
            in_pkg = False
        if in_pkg and line.startswith("version"):
            line = f'version = "{ver}"'
        lines.append(line)
    cargo.write_text("\n".join(lines) + "\n")
print(ver)
PY
}

bump_version() {
  local kind="$1"
  local cur
  cur="$(read_version)"
  python3 - "$cur" "$kind" <<'PY'
import sys
maj, minor, patch = (int(x) for x in sys.argv[1].split(".", 2))
kind = sys.argv[2]
if kind == "major":
    maj, minor, patch = maj + 1, 0, 0
elif kind == "minor":
    minor, patch = minor + 1, 0
elif kind == "patch":
    patch += 1
else:
    raise SystemExit(f"bad bump kind: {kind}")
print(f"{maj}.{minor}.{patch}")
PY
}

if [ -n "$BUMP" ]; then
  NEW_VER="$(bump_version "$BUMP")"
  set_version "$NEW_VER" >/dev/null
  git add package.json src-tauri/tauri.conf.json src-tauri/Cargo.toml
  git commit -m "Bump version to ${NEW_VER}"
  echo "Bumped version to ${NEW_VER}"
fi

VERSION="$(read_version)"
TAG="v${VERSION}"
OUT_DIR="$ROOT/releases/${TAG}"
APP_SRC="$ROOT/src-tauri/target/release/bundle/macos/Focal Point Aligner.app"
APP_DST="$OUT_DIR/Focal Point Aligner.app"

if [ "$SKIP_BUILD" -eq 0 ]; then
  ./build_macos.sh
fi

if [ ! -d "$APP_SRC" ]; then
  echo "Missing app bundle: $APP_SRC" >&2
  echo "Run ./build_macos.sh first (or omit --skip-build)." >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
rm -rf "$APP_DST"
ditto "$APP_SRC" "$APP_DST"

{
  echo "Focal Point Aligner ${TAG}"
  echo "built: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commit: $(git rev-parse HEAD)"
  echo "branch: $(git rev-parse --abbrev-ref HEAD)"
  echo ""
  echo "Open:"
  echo "  open \"$APP_DST\""
  echo "  # or: ./scripts/open-app.sh"
  echo ""
  echo "Needs this checkout + ./venv (FPA_ROOT is set by open-app.sh)."
  echo "Unsigned: first open via Finder → right-click → Open."
} >"$OUT_DIR/NOTES.txt"

ln -sfn "$TAG" "$ROOT/releases/latest"

if [ "$SKIP_TAG" -eq 0 ]; then
  if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "Local tag ${TAG} already exists — leaving it as-is."
  else
    git tag -a "$TAG" -m "Local release ${TAG}"
    echo "Created local tag ${TAG} (not pushed)."
  fi
fi

echo ""
echo "Release ready (local only):"
echo "  $APP_DST"
echo "  $ROOT/releases/latest -> $TAG"
echo "Open with: ./scripts/open-app.sh"
