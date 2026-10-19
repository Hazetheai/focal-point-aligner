# Local releases (gitignored)

Unsigned desktop builds stay on this machine under `releases/`. Nothing is
uploaded to GitHub, Apple, or Microsoft.

## One-time setup (macOS release branch)

```bash
./scripts/install-git-hooks.sh
git branch release   # once; tracks what you ship locally
```

## Ship a macOS build

From any feature work already on `main`:

```bash
git checkout release
git merge main
```

The `post-merge` hook runs `./scripts/release.sh`, which:

1. Builds the unsigned Tauri app (`./build_macos.sh`)
2. Copies it to `releases/vX.Y.Z/Focal Point Aligner.app`
3. Points `releases/latest` at that version
4. Creates a **local** git tag `vX.Y.Z` (does not push)

Skip the auto-build for a merge:

```bash
FPA_SKIP_RELEASE=1 git merge main
```

Or release manually anytime:

```bash
./scripts/release.sh
./scripts/release.sh --bump patch   # bump package + tauri version, commit, then build
```

Open:

```bash
./scripts/open-app.sh
```

First Gatekeeper open: Finder → right-click the `.app` → **Open**.
The app still needs this checkout + `./venv`.

## Ship a Windows build

On a Windows machine with MSVC Build Tools, WebView2, Rust, Node, and Python:

```powershell
.\scripts\release.ps1
.\scripts\open-app.ps1
```

This builds the unsigned NSIS installer (`.\scripts\build_windows.ps1`), copies it
into `releases\vX.Y.Z\`, and updates `releases\latest`. Version bumps can still
use `./scripts/release.sh --bump` on macOS (or edit `package.json` /
`src-tauri/tauri.conf.json` / `src-tauri/Cargo.toml` by hand) before running
`release.ps1`.

SmartScreen may warn on first run (unsigned). The bare NSIS/exe still needs this
checkout + `.\venv`, or `FPA_ROOT` / `FPA_PYTHON`.

### Portable zip for a collaborator (recommended for sharing)

No signing license. Includes exe + Python modules + a local `venv`:

```powershell
.\scripts\pack_windows_portable.ps1
```

Send `releases\FocalPointAligner-portable-vX.Y.Z.zip`. Recipient unzips and runs
**Start.bat**. They do not need git or npm. Video still needs ffmpeg on PATH.

## Later (optional)

When you want shared/CI releases, add a remote workflow that publishes the same
artifacts; keep this local path until then.
