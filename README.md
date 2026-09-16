# Focal Point Aligner

Align a folder of photos around a focal point, then export them to a shared frame size.

The GUI is a **React + FastAPI** app. On macOS you can also run an unsigned **Tauri** `.app` shell that embeds the web UI and starts the Python API from this project’s `./venv`.

## Run (development)

Needs **Node.js** and **Python 3**. From the repo root:

```bash
npm run dev
```

Creates `./venv` if needed, installs deps, starts the API on **8765**, Vite on **5173**, and opens the browser. Stop with Ctrl+C.

Equivalent: `./dev.sh`

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

1. **Opener** — Single / Batch / **Import**. Set target size with ratio + resolution presets (or manual W×H) → **Start**.
2. **Original** — click/drag focal; wheel resizes crop; **Enter** saves+advances; **X** / **Shift+middle-click** discards; **D** duplicates.
3. **Preview** — pan/zoom fine-tune; **Enter** commits; **C** compares; live zoom indicator.
4. **Arrange** — drag thumbs; AutoArrange (Color / Depth / Lead / Faces); **Reverse**; slots **0–9**.
5. **E** / Export writes numbered JPEGs; focals stay in `<input>/focal_points.json`.
6. **Esc** returns to the opener (batch → next folder).

## Keyboard

| Key | Action |
|-----|--------|
| Enter | Original: save+next · Preview: commit draft |
| Space / ← → | Skip / navigate |
| X / Shift+middle click | Discard |
| D | Duplicate (Original) |
| H / G / I | Home / Grid / Mask |
| C | Compare (Preview or Arrange) |
| 0–9 | Arrange slots |
| P / O / A | Preview / Orient / Arrange |
| R / E / Esc | Reset / Export / Opener |

Hotkeys are tab-scoped.

## Batch, import, merge

- **Batch** walks subfolders; done when `<sub>_aligned` already has images.
- **Import** downloads URL lists, then continues as Batch.
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
| `scripts/open-app.sh` | Open release `.app` with `FPA_ROOT` |
| `build_macos.sh` | Unsigned Tauri release build |
| `api/app.py` | FastAPI |
| `web/` | React UI |
| `aligner_core.py` | Crop / state / export |
| `arrange_auto.py` | AutoArrange |
| `import_download.py` | URL download |
| `batch.py` | Batch / merge / move |
| `cli.py` | CLI |
| `src-tauri/` | Tauri 2 shell |

Agent notes: [`AGENTS.md`](AGENTS.md).

## License

Internal use — Ceangailte Software
