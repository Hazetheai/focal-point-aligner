# AGENTS.md

Guidance for AI agents (or humans) working on this project. Read this before making changes.

## What this project is

**Focal Point Aligner** — click a focal point on each photo in a folder; export aligned JPEGs at a shared target size with that point centered.

Current GUI: **React (Vite) + FastAPI**, optional Tauri shell. PyQt6 in `main.py` / `ui/` is **legacy**.

Workflow:

1. Opener: pick input folder → target width/height → **Start** (or Batch on a root of subfolders).
2. **Original**: click focal point; Enter / double-click saves and advances; **X** / middle-click discards. Resizable prev / current / next columns; expandable image facts (path: first click expands, second copies).
3. **Preview**: aligned crop of the **same** `current_idx` as Original / Arrange. No saved focal → show original; never persist a silent center focal from preview generation.
4. **Arrange**: drag thumbnails to set export order; **Original** / **Aligned** thumb toggle. Selection follows the file, not the old slot.
5. **F** / Export writes `{idx:04d}.jpg` to the output folder.
6. **Esc** (or Done) returns to the opener; in batch mode it opens the next pending folder.

## One command for the GUI

```bash
npm run dev
```

(`./dev.sh` is the same.) Creates `./venv` if needed, installs Python + `web/` deps, starts FastAPI on **8765**, Vite on **5173**, opens the browser. Requires Node.js and Python 3. Do not tell people to run `main.py` unless they explicitly want the old PyQt app.

Opener **Browse** buttons open a native **folder** picker (via `POST /dialog/folder`, or Tauri when running as a desktop shell). They never pick files. In batch mode, Browse + Refresh load the subfolder queue; Merge / Move aligned / Start Batch use that queue.

## Focal clicks (Original tab)

- Left click = pending focal (crosshair + crop overlay).
- Double-click or **Enter** = save + advance (`set_focal` then `confirm_and_save`).
- Switching to Preview with a pending click **saves without advancing** so Preview is the same image.
- Right click = image center as pending (`auto_center`); right **double-click** confirms that center focal and advances.
- Middle click = discard current image.
- Coordinates must come from the **displayed** image (`naturalWidth` / canvas bounding rect), not a stale session size. Python load/probe applies **EXIF orientation** so clicks match `cv2` pixels.
- After a click, draw a dim overlay **outside** `compute_crop` with a white border so the keep-region (crop or upscale cover) is visible. No zoom-drag overlay.
- Original stage: show the photo as a visible `<img>`; canvas is a transparent overlay for crosshair/crop only. Do not paint from a `display:none` image (cached loads skip `onLoad` and leave a blank stage).
- Header filename truncates; tabs stay in a fixed center column so layout does not jump between images.
- Image facts **Path**: truncated by default; first click expands full path; second click copies; closing Details resets truncation.

## Stack & tests

- Python 3.x, FastAPI, uvicorn, opencv-python, numpy, pillow. See `requirements.txt`.
- Web: Vite + React in `web/`. Root `package.json` only launches the stack / Tauri.
- Venv lives at `./venv` (gitignored). No system Python on the original machine had deps.
- Tests: `./venv/bin/python -m pytest tests/ -v`
- Qt tests (arrange grid, return-to-opener) need `QT_QPA_PLATFORM=offscreen`.
- **Do not read `pyqt_aligner.log` wholesale** — it can be tens of MB. Gitignored; safe to delete.

## Architecture / where things live

| Path | Role |
|------|------|
| `scripts/dev.sh` | GUI launcher used by `npm run dev` |
| `api/app.py` | FastAPI: session, focals, navigate, discard, order, export SSE, media, batch/merge, folder dialog |
| `web/src/Opener.jsx` | Folder picker, single/batch, merge/move |
| `web/src/Aligner.jsx` | Original / Preview / Arrange (original vs aligned thumbs), nav dots, hotkey strip |
| `web/src/crop.js` | JS port of `compute_crop` |
| `aligner_core.py` | **UI-free core** — state, persistence, crop, discard, reorder, export. No Qt. |
| `batch.py` | **UI-free batch** — discovery, done-detection, `merge_folders()`, `move_aligned_outputs()` |
| `cli.py` | Thin CLI over the core |
| `src-tauri/` | Optional Tauri 2 shell |
| `main.py`, `ui/` | **Legacy PyQt GUI**. Edit only if asked. |
| `align_focal_points.py`, `ui/closer_screen.py`, `ui/main_window.py` | Older unused reference. |

## Core state (`FocalPointAlignerCore`)

- `image_files: list[Path]` — export order. **Order lives here; files on disk stay as-is.**
- `focal_points: dict[int, tuple]` — index → `(fx, fy)` in **oriented** original pixels (EXIF applied).
- `completed: set[int]`, `auto_center_flags`, `image_dimensions`, `preview_dirty`.
- `discarded: set[str]` — filenames.
- `current_idx: int` — shared across Original / Preview / Arrange. Tab switches must not change it.
- `json_path` = `<output_folder>/focal_points.json`.
- Session images also expose `bytes`, `dpi`, `format`, `mode`, `megapixels`, `auto_center`, `focal_at_center`.

### Persistence (`focal_points.json`)

- Focals keyed by **filename** (`focal_x`, `focal_y`, `original_width/height`, `auto_center`, `timestamp`).
- Top-level: `discarded`, `order` (filenames), `current_idx`, `alignment_mode`, `preview_state`, `_meta`.
- `load_focal_points()` re-applies `order` via `_reorder_files_by_names()`.
- Thumbs/previews: `<input>/.fpa_cache/` keyed by **filename**, not index (reorder must not reuse the wrong JPEG). Media URLs should cache-bust with `?n=<filename>`.
- `config.json` at repo root: opener prefs. Gitignored.

## Arrange / reorder invariants

1. **`apply_arrange_order(order)`** takes `new_position → old_index`, requires `len(order) == len(image_files)`, returns `False` on mismatch.
2. After a successful reorder, **`current_idx` must follow the same file** (`old_to_new[old_current]`). Silent slot-stay was a bug: Original/Preview showed a different image.
3. **Export order == `image_files` order.** Slot `i` is `image_files[i]` with `focal_points[i]`.
4. **Discards** move the file to `<input>/discarded/` and compact all index dicts (no gaps).
5. Web Arrange uses **filename** as the dnd-kit id (indices remapped 0..n-1 after save). Optimistic reorder then `POST /order`.

## Keyboard

`Enter` save+next · `Space` skip · `←→` navigate (no wrap) · `X` discard · `Del` clear · `P` preview · `O` orientation · `A` arrange · `[`/`]` shift order · `R` reset · `F` export · `Esc` opener / next batch.

Mouse on Original: left click pending · left double save+next · right click center pending · right double center save+next · middle click discard.

## Image-size framing (crop math)

- `compute_crop(fx, fy, orig_w, orig_h, target_w, target_h)` — focal centered, clamped at edges.
  - Source ≥ target in both dims: **1:1** crop of `(target_w, target_h)`.
  - Source smaller on either side: scale up just enough to **cover**, then crop.
- `render_aligned()` crops that rect and resizes to the target. No blur-fill, no max-zoom overlay.
- After a focal is pending or saved, Original draws that rect as a dim outside-region + white border (not a zoom control).
- `ensure_preview_for_current` / Arrange aligned thumbs may render with a display-only center when unset, but must **not** write `focal_points` / `auto_center_flags`.
- `max_zoom` remains on the API/config for compatibility; it does **not** change framing.
- Tests: `tests/test_crop_math.py` (including “focal lands at output center”).

## Pagination

- Pages of **10** images. Page chips first, then the 10 dots for the current page.
- Dot states: unset (gray), focal set (green), center/default focal (gray with green core), current (blue).
- Center = `auto_center` or `focal_at_center` (focal within 1px of image center).

## Tab / selection sync

- One `current_idx` for Original, Preview, Arrange, nav dots, discard.
- Arrow keys do not wrap on any tab (stops at ends). Preview wrap was making tabs feel “on a different image”.
- Discard (`POST /discard?index=`) uses that index; all lists compact together.

## Batch mode

- Opener `mode` `"single"` / `"batch"` in `config.json`.
- Auto-advance: next pending subfolder whose `<sub>_aligned` does **not** already contain images.
- Do not loop on escaped batches: skip folders already opened this session; Esc without export leaves the folder pending (focals survive in that folder’s `focal_points.json`).
- Merge (`batch.merge_folders`) prefixes `<source>_`; `delete_sources=True` only after success.
- Move aligned: `<sub>_aligned` → sibling `<root>_aligned`.
- List shows image-bearing subfolders including `*_aligned` (`done=True`); auto-advance never re-opens those.

## Testing

- `tests/test_cli.py` — CLI subprocess (venv Python).
- `tests/test_crop_math.py` — crop / render_aligned.
- `tests/test_api.py` — FastAPI session, media, export, navigate no-op at ends.
- `tests/test_core_io.py` — header probe, EXIF size, filename-keyed cache, confirm does not write full-res.
- `tests/test_batch.py` — discovery, merge, move-aligned.
- `tests/test_arrange_order.py` — discard → reorder → persist; **current_idx follows the file**.
- `tests/test_return_to_opener.py` — PyQt return-to-opener + batch auto-advance.
- Run: `./venv/bin/python -m pytest tests/ -v`

## Building

- Dev GUI: `npm run dev`
- Tauri window: `npm run desktop`
- Tauri release: `npm run build`
- Legacy PyInstaller: `./build_macos.sh` → `dist/FocalPointAligner.app`

## Conventions

- Crop/reorder/export logic stays in `aligner_core.py` (no Qt, no React).
- Prefer remapping index dicts from filenames after discard/reorder over ad-hoc UI rebuilds.
- Keep Original / Preview / Arrange on the same `current_idx`.
- Preview/media generation must not invent saved focals for unset images.
