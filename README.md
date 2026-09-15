# Focal Point Aligner

Align a folder of photos around a focal point, then export them to a shared frame size.

The current GUI is a React app with a FastAPI backend (optional Tauri desktop shell). Click a point on each image; export crops around that point so it sits in the center of the target frame.

## Run the GUI

Needs **Node.js** and **Python 3**. From the repo root:

```bash
npm run dev
```

That creates the Python venv if needed, installs deps, starts the API, and opens **http://localhost:5173**. Stop with Ctrl+C.

Equivalent: `./dev.sh`

## How it works

1. Pick an input folder (and optional output folder) → set target width/height → **Start**.
2. **Original** tab: click to set a focal point. Scroll the wheel to resize the crop box (aspect locked). **Enter** or double-click saves and goes to the next image. **X** / **Shift+middle-click** discards. Prev / current / next columns are resizable (current larger by default). **Details** expands image metadata; the path expands on first click and copies on the second.
3. **Preview** tab: the aligned crop of the same image. Drag to fine-tune the focal; middle-drag or wheel to zoom; **`<`** fades the previous image on top, **`>`** fades the next. **Compare** toggles saved vs draft; **Commit** writes the fine-tune. If no focal is set yet, it shows the original instead of inventing one.
4. **Arrange** tab: drag thumbnails to set export order. Toggle **Original** / **Aligned** thumbs. The selected image is the one Original/Preview show.
5. **F** (or Export) writes `{0000,0001,...}.jpg` into the output folder.
6. **Esc** returns to the opener so you can process another folder.

Cropping is straightforward: the focal point is centered in the output (clamped at edges). Large photos take a native-pixel crop of the target size; small photos are scaled up to fill the frame. A click shows that keep-region as a dim overlay with a white border. EXIF orientation is applied so the click matches the pixels that get cropped.

Browse always opens a **folder** picker (not files). Nav dots are pages of 10; unset / focal-set / center states are color-coded.

## Keyboard

| Key | Action |
|-----|--------|
| Enter | Save focal and go to next |
| Space / ← → | Skip / navigate (stops at the ends) |
| X / Shift+middle click | Discard current image |
| Wheel (Original) | Resize crop box (aspect locked) |
| Right click | Pending focal at image center |
| Right double-click | Save center focal and go to next |
| G | Toggle rule-of-thirds grid (Original / Preview) |
| Middle-drag / wheel (Preview) | Zoom crop in Preview |
| `<` `>` | Preview: fade previous / next image on top |
| Del | Clear focal |
| P | Preview tab |
| O | Landscape / portrait |
| A | Arrange tab |
| [ ] | Shift current image in the order |
| R | Reset all focals |
| F | Export |
| Esc | Back to opener (or next batch folder) |

The same actions are on the hotkey strip at the bottom of the aligner.

## Batch, merge, move aligned

- **Batch** mode walks subfolders of a root. After export (or Esc), the next pending folder opens. A folder is done when its `<sub>_aligned` output already has images.
- **Merge** copies from several folders into one, prefixing filenames with the source folder name.
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
| `api/app.py` | FastAPI session, media, export, batch |
| `web/` | React UI (opener, original / preview / arrange) |
| `aligner_core.py` | UI-free state, crop math, persist, export |
| `batch.py` | Folder discovery, merge, move-aligned |
| `cli.py` | CLI over the same core |
| `src-tauri/` | Optional Tauri shell |
| `ui/`, `main.py` | Legacy PyQt GUI |

Config (`config.json`) is gitignored and stores last folders and target size. Focal data lives in `<output_folder>/focal_points.json`. Thumbs/previews are in `<input>/.fpa_cache/`.

## License

Internal use — Ceangailte Software
