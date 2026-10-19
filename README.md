# Focal Point Aligner

Align a folder of photos (and videos) around a focal point, then export them to a shared frame size.

The GUI is a **React + FastAPI** app with light/dark theme. An unsigned **Tauri** desktop shell (macOS `.app` / Windows NSIS) embeds the web UI and starts the Python API from this project’s `./venv`.

End-user docs ship with the app (**Help** menu / in-app Help button). Source: [`docs/user/`](docs/user/).

## Prerequisites

| | Dev (`npm run dev`) | Desktop build |
|-|---------------------|---------------|
| Node.js 18+ | yes | yes |
| Python 3.10+ | yes | yes |
| Rust / Cargo | — | yes |
| ffmpeg on `PATH` | for video | for video |
| macOS | Xcode CLT recommended | same |
| Windows | — | MSVC Build Tools + WebView2 |

Video: `brew install ffmpeg` (macOS) or install ffmpeg and add it to PATH (Windows).

## Run (development)

From the repo root (macOS, Linux, or Windows):

```bash
npm run dev
```

Creates `./venv` if needed, installs deps, starts the API on **8765**, Vite on **5173**, and opens the browser. Stop with Ctrl+C.

`npm run dev` is cross-platform: Unix uses `scripts/dev.sh`, **native Windows PowerShell** uses `scripts/dev.ps1` (no WSL required).

**Windows (PowerShell)** — after installing Node 18+ and Python 3.10+ with “Add to PATH”:

```powershell
cd FocalPointAligner
npm install
npm --prefix web install
npm run dev
# or: .\scripts\dev.ps1
```

## Desktop app (unsigned Tauri)

The desktop shell still needs **this checkout + `./venv`**. Set `FPA_ROOT` (and optionally `FPA_PYTHON`) if you move the app away from the repo. Use the open helpers below — they set `FPA_ROOT` for you.

### macOS

```bash
./build_macos.sh          # or: npm run build
./scripts/open-app.sh     # sets FPA_ROOT and opens the .app
```

Output: `src-tauri/target/release/bundle/macos/Focal Point Aligner.app`

- **Unsigned:** first launch via Finder → right-click → **Open** (Gatekeeper).
- Dev window without a full release build: `npm run desktop`.

### Windows

```powershell
.\scripts\build_windows.ps1
.\scripts\open-app.ps1
```

Output: NSIS installer under `src-tauri\target\release\bundle\nsis\`.

- **Unsigned:** SmartScreen may warn on first run.
- Requires [MSVC Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/), WebView2 (usually preinstalled on Windows 10/11), and Rust.
- Stage NSIS into `releases\`: `.\scripts\release.ps1`

#### Share a standalone zip (no git / npm for the recipient)

For handing the app to someone on Windows (no paid signing cert needed — SmartScreen may still warn once):

```powershell
.\scripts\pack_windows_portable.ps1
```

Creates `releases\FocalPointAligner-portable-vX.Y.Z\` and a matching `.zip` that includes:

- the Tauri `.exe`
- the Python API + core modules
- a Windows `venv` with dependencies

They unzip, double-click **Start.bat**, and run. Video still needs **ffmpeg** on their PATH. Build this pack **on Windows** (native PowerShell), not under WSL.

There is no PyQt / PyInstaller app path anymore.

## How it works

1. **Opener** — Single / Batch / **Import**. Set target size with ratio + resolution presets (or manual W×H) → **Start**. Header theme toggle switches light/dark (also follows system when preference is “system”).
2. **Original** — click/drag focal; wheel resizes crop; **Enter** saves+advances; **X** / **Shift+middle-click** discards; **D** / action-bar Duplicate (right-aligned). Stage uses a theme-aware checkerboard. Videos: scrubber for work / in / out; **Shift+click** adds a keyframe; marker click sets ease; **Del** clears all keyframes.
3. **Preview** — pan/zoom fine-tune; Flip X / Flip Y; Overlay prev/clear/next (screen-centered); Compare (**C**) + Commit (**Enter**); Wrap for looping ←→. Videos: **Play** / **Space**; **Keyframes** popover shows `selected/total` and picks by ordinal.
4. **Arrange** — Original/Aligned thumbs; Reverse; slots **0–6**; AutoArrange Color / Depth / Lead / Faces on the action bar; drag to reorder (video thumbs show ▶).
5. **E** / Export writes `{idx:04d}.jpg` for images and `{idx:04d}.mp4` for videos (ffmpeg); focals stay in `<input>/focal_points.json`.
6. **Esc** returns to the opener (batch → next folder).

Supported stills: `.jpg` `.jpeg` `.png` `.bmp` `.webp` `.tiff`. Videos: `.mp4` `.mov` `.m4v` `.webm` `.hap`.

## Keyboard

| Key | Action |
|-----|--------|
| Enter | Original: save+next · Preview: commit draft |
| Space | Original: skip · Preview video: play/pause |
| ← → | Navigate (Preview can Wrap) |
| X / Shift+middle click | Discard |
| D | Duplicate (Original) |
| Del | Clear focal (images) / clear all keyframes (videos) |
| H / G / I | Home / Grid / Mask |
| C | Compare (Preview) |
| `<` `>` | Overlay neighbor (Preview) |
| 0–6 | Arrange slots |
| P / O / A | Preview / Orient / Arrange |
| R / E / Esc | Reset / Export / Opener |

Hotkeys are tab-scoped. Discard / Del / Reset are marked as destructive in the hotkey bar.

## Batch, import, merge

- **Batch** walks subfolders; done when `<sub>_aligned` already has media.
- **Import** downloads pasted URLs, a `.txt` list, or a folder of lists, then continues as Batch. List filenames are parsed with a user-defined pattern (default `image_urls--{name}` → folder `name/`); prefix/suffix around `{name}` are editable in the Opener and stored as `import_name_pattern` in prefs.
- **Merge** / **Move aligned** as before.

## CLI

```bash
./focalpoint init --input /path/to/images --output /path/to/output
# or: ./venv/bin/python cli.py …
```

Windows: `venv\Scripts\python cli.py init --input C:\path\to\images --output C:\path\to\output`

## Tests

```bash
./venv/bin/python -m pytest tests/ -v
```

## Layout

| Path | Role |
|------|------|
| `scripts/dev.sh` | Dev launcher (`npm run dev`) |
| `scripts/open-app.sh` | Open latest local macOS release `.app` with `FPA_ROOT` |
| `scripts/open-app.ps1` | Open latest Windows release exe with `FPA_ROOT` |
| `scripts/release.sh` | Local unsigned macOS release into `releases/` |
| `scripts/release.ps1` | Local unsigned Windows NSIS copy into `releases/` |
| `build_macos.sh` | Unsigned Tauri macOS build |
| `scripts/build_windows.ps1` | Unsigned Tauri Windows NSIS build |
| `docs/user/` | End-user Help guides (bundled with the app) |
| `api/app.py` | FastAPI |
| `web/` | React UI |
| `web/src/Help.jsx` | In-app Help viewer |
| `web/src/theme.js` | Light / dark / system theme preference |
| `aligner_core.py` | Crop / state / export / video keyframes |
| `arrange_auto.py` | AutoArrange |
| `import_download.py` | URL download + list naming patterns |
| `batch.py` | Batch / merge / move |
| `cli.py` | CLI |
| `src-tauri/` | Tauri 2 shell (macOS + Windows) |

## Local desktop releases

Unsigned builds stay on this machine (no GitHub/Apple/Microsoft publish):

**macOS**

```bash
./scripts/install-git-hooks.sh   # once
git checkout release && git merge main   # builds into releases/
# or: ./scripts/release.sh --bump patch
./scripts/open-app.sh
```

**Windows**

```powershell
.\scripts\release.ps1
.\scripts\open-app.ps1
```

Details: [`docs/LOCAL_RELEASES.md`](docs/LOCAL_RELEASES.md).

Agent notes: [`AGENTS.md`](AGENTS.md). Legacy Windows notes redirected from [`WINDOWS_SETUP.md`](WINDOWS_SETUP.md).

## License

Internal use — Ceangailte Software
