# Focal Point Aligner

Align a folder of photos around a focal point, then export them to a shared frame size.

The current GUI is a React app with a FastAPI backend (optional Tauri desktop shell). Click a point on each image; export crops around that point so it sits in the center of the target frame.

## Run the GUI

Needs **Node.js** and **Python 3**. From the repo root:

```bash
npm run dev
```

That creates the Python venv if needed, installs deps, starts the API on **8765**, Vite on **5173**, and opens the browser. Stop with Ctrl+C.

Equivalent: `./dev.sh`

## How it works

1. **Opener** — Single / Batch / **Import**. Set target size with ratio + resolution presets (or manual W×H) → **Start**. Import pastes URLs or picks a `.txt` / folder of lists, downloads into a batch root, then continues as Batch.
2. **Original** — click/drag to set a focal; wheel resizes the crop box (aspect locked). **Enter** or double-click saves and advances. **X** / **Shift+middle-click** discards. **D** duplicates the current file on disk. Header can retarget size mid-session. **Guides** drawer: rule-of-thirds grid (**G**) and optional composition mask (**I**).
3. **Preview** — aligned crop of the same image. Drag to pan; middle-drag / wheel to zoom (`crop_scale`). **Enter** commits a dirty draft; **C** compares saved vs draft. Live zoom indicator in the toolbar. **Wrap** toggles whether ←→ loop the list.
4. **Arrange** — drag thumbnails (multi-select with Cmd/Ctrl or Shift). AutoArrange: **Color**, **Depth near→far**, **Lead match**, **Faces** (SSE progress above the buttons). **Reverse** flips the active slot in place (button stays lit while reversed). Slots **0–9**; **C** compares two slots.
5. **E** / Export writes `{0000,0001,…}.jpg` with live progress. `focal_points.json` is kept in the **input** folder.
6. **Esc** / Done returns to the opener; in batch mode opens the next pending folder.

Cropping keeps the focal centered (never letterboxes). Large photos take a native-pixel crop of the target size; small or edge focals scale up to cover. Wheel zoom and edge-forced magnification bake into per-image `crop_scale`. EXIF orientation is applied so clicks match the pixels that get cropped. High-bit-depth sources are normalized to 8-bit for preview/export.

Browse opens a **folder** picker (Import can also pick a `.txt`). Nav dots are pages of 10.

## Keyboard

| Key | Action |
|-----|--------|
| Enter | Original: save+next · Preview: commit draft (when dirty) |
| Space / ← → | Skip / navigate (stops at ends; Preview can Wrap) |
| X / Shift+middle click | Discard |
| D | Duplicate current image (Original) |
| Wheel (Original) | Resize crop box |
| Right click / right double | Center pending / save center+next |
| H | Home: center focal + reset crop scale |
| G / I | Grid / composition mask |
| Middle-drag / wheel (Preview) | Zoom |
| `<` `>` | Preview: fade previous / next |
| C | Preview or Arrange: compare |
| 0–9 | Arrange: recall slots |
| Del | Clear focal |
| P / O / A | Preview / Orient / Arrange |
| R | Reset all focals |
| E | Export |
| Esc | Opener (or next batch folder) |

Hotkey chips are **tab-scoped** — keys not shown for the current tab do nothing.

## Batch, import, merge

- **Batch** walks subfolders of a root. After export (or Esc), the next pending folder opens. Done when `<sub>_aligned` already has images.
- **Import** downloads URL lists into named folders under a dest root, then hands off to Batch.
- **Merge** copies from several folders into one, prefixing with the source folder name.
- **Move aligned** gathers `<sub>_aligned` folders into a sibling `<root>_aligned`.

## CLI

```bash
./venv/bin/python cli.py init --input /path/to/images --output /path/to/output
./venv/bin/python cli.py set-focal --x 1280 --y 720
./venv/bin/python cli.py save
./venv/bin/python cli.py export --orientation landscape
```

Other commands: `status`, `navigate`, `skip`, `clear-focal`, `discard`, `reset`, `stats`, `list-images`, `get-image`, `order`, `move-image`, `merge`, `move-aligned`, `batch-list`. Most accept `--json`.

## Tests

```bash
./venv/bin/python -m pytest tests/ -v
```

GUI-related Qt tests still need a headless platform if you hit them:

```bash
QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/ -v
```

## Desktop .app (optional)

```bash
npm run desktop   # Tauri window in dev
npm run build     # Tauri release build
```

The legacy PyQt app is still at `./venv/bin/python main.py`. The supported GUI is `npm run dev`.

## Layout

| Path | Role |
|------|------|
| `scripts/dev.sh` | One-command GUI launcher (`npm run dev`) |
| `api/app.py` | FastAPI: session, media, export/import/arrange SSE, batch |
| `web/` | React UI (opener, original / preview / arrange) |
| `web/src/presets.js` | Size ratio + resolution presets |
| `aligner_core.py` | UI-free state, crop math, persist, export |
| `arrange_auto.py` | Color / depth / lead / faces AutoArrange |
| `import_download.py` | URL-list download helpers |
| `batch.py` | Folder discovery, merge, move-aligned |
| `cli.py` | CLI over the same core |
| `src-tauri/` | Optional Tauri shell |
| `ui/`, `main.py` | Legacy PyQt GUI |

Config (`config.json`) is gitignored and stores last folders and target size. Focal data lives in `<input_folder>/focal_points.json`. Thumbs/previews are in `<input>/.fpa_cache/`. Depth/face ONNX models cache under `.fpa_models/`.

Agent/dev notes: see [`AGENTS.md`](AGENTS.md).

## License

Internal use — Ceangailte Software
