# Focal Point Aligner

Align a folder of photos (and videos) around a focal point, then export them to a shared frame size.

The GUI is a **React + FastAPI** app with light/dark theme. On macOS you can also run an unsigned **Tauri** `.app` shell that embeds the web UI and starts the Python API from this project’s `./venv`.

## Run (development)

Needs **Node.js** and **Python 3**. From the repo root:

```bash
npm run dev
```

Creates `./venv` if needed, installs deps, starts the API on **8765**, Vite on **5173**, and opens the browser. Stop with Ctrl+C.

Equivalent: `./dev.sh`

**Video** (scrub, keyframes, export) needs system **ffmpeg** on your `PATH` (`brew install ffmpeg` on macOS). OpenCV is used first for frames; ffmpeg is the fallback for codecs OpenCV cannot open (e.g. HAP).

## Desktop app (unsigned Tauri)

```bash
./build_macos.sh          # or: npm run build
./scripts/open-app.sh     # sets FPA_ROOT and opens the .app
```

Output:

`src-tauri/target/release/bundle/macos/Focal Point Aligner.app`

- **Unsigned:** first launch via Finder → right-click → **Open** (Gatekeeper). After that, normal double-click works.
- The `.app` still needs **this checkout + `./venv`**. Set `FPA_ROOT` if you move the `.app` away from the repo (or use `./scripts/open-app.sh`).
- Dev window without a full release build: `npm run desktop`.

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

## Tests

```bash
./venv/bin/python -m pytest tests/ -v
```

## Layout

| Path | Role |
|------|------|
| `scripts/dev.sh` | Dev launcher (`npm run dev`) |
| `scripts/open-app.sh` | Open latest local release `.app` with `FPA_ROOT` |
| `scripts/release.sh` | Local unsigned release into `releases/` |
| `build_macos.sh` | Unsigned Tauri build |
| `api/app.py` | FastAPI |
| `web/` | React UI |
| `web/src/theme.js` | Light / dark / system theme preference |
| `aligner_core.py` | Crop / state / export / video keyframes |
| `arrange_auto.py` | AutoArrange |
| `import_download.py` | URL download + list naming patterns |
| `batch.py` | Batch / merge / move |
| `cli.py` | CLI |
| `src-tauri/` | Tauri 2 shell |

## Local desktop releases

Unsigned `.app` builds stay on this machine (no GitHub/Apple publish):

```bash
./scripts/install-git-hooks.sh   # once
git checkout release && git merge main   # builds into releases/
# or: ./scripts/release.sh --bump patch
./scripts/open-app.sh
```

Details: [`docs/LOCAL_RELEASES.md`](docs/LOCAL_RELEASES.md).

Agent notes: [`AGENTS.md`](AGENTS.md).

## License

Internal use — Ceangailte Software
