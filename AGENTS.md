# AGENTS.md

Guidance for AI agents (or humans) working on this project. Read this before making changes.

## What this project is

**Focal Point Aligner** — a PyQt6 desktop app that aligns a batch of images around a focal point. Workflow:

1. Pick an input folder (drag-and-drop or Browse) → set target dimensions → **Start**.
2. Set a focal point on each image (click), then **Save** to advance; discard bad images (`X`).
3. **Arrange** tab: drag-and-drop thumbnails to choose the final order.
4. Press **F** → **Export** writes aligned images to the output folder.
5. After export (or after quitting a batch with **Escape**), the app **returns to the opener screen** so you can immediately process another folder. Close the opener window to quit.

## Stack & setup

- Python 3.x, PyQt6, opencv-python (cv2), numpy, pillow. See `requirements.txt`.
- No system Python on this machine has the deps installed. Create a venv to run the app/tests:
  ```bash
  python3 -m venv venv
  ./venv/bin/pip install -r requirements.txt pytest
  ./venv/bin/python main.py
  ```
- GUI tests need a headless Qt platform:
  ```bash
  QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/ -v
  ```
- **Do not read `pyqt_aligner.log` wholesale** — it grows to tens of MB. It is gitignored and safe to delete.

## Architecture / where things live

| Path | Role |
|------|------|
| `main.py` | Entry point. `FocalPointAlignerApp(QApplication)` wires screens. Owns the return-to-opener AND batch auto-advance flows. |
| `aligner_core.py` | **UI-free core** — `FocalPointAlignerCore`. All state, persistence, image math, discard/reorder/export helpers. |
| `batch.py` | **UI-free batch core** — `BatchManager` (discovery, done-detection, queue) + `merge_folders()` + `move_aligned_outputs()`. No Qt imports. |
| `cli.py` | Thin CLI mirroring core operations (init/status/set-focal/navigate/discard/export...). |
| `ui/opener_screen.py` | Folder selection screen; Single/Batch toggle; batch list + merge/move controls; reads/writes `config.json`. |
| `ui/aligner_screen.py` | Main screen with 3 tabs: **Original** (thumbnails + focal clicks), **Preview**, **Arrange**. |
| `ui/arrange_grid.py` | `ArrangeGridWidget`: draggable thumbnail grid for reordering + `ArrangeThumbnailWidget`. |
| `ui/end_menu.py` | Export dialog (orientation, output folder, progress). |
| `ui/merge_dialog.py` | Folder-merge dialog (multi-source, prefix naming, aligned-output option). |
| `ui/navigation_dots.py` | Dot strip for navigation + drag-reorder. |
| `ui/thumbnail_widget.py`, `ui/image_display.py`, `ui/preview_worker.py` | Support widgets / async previews. |
| `ui/logger.py` | Logging (writes `pyqt_aligner.log` in the cwd). |
| `styles.py` | Color palette / widget styles. |
| `scripts/align_and_scale_images.py` | Legacy batch processor (not used by the GUI). |
| `align_focal_points.py`, `ui/closer_screen.py`, `ui/main_window.py` | **Legacy / unused**, preserved as reference. Edit only if asked. |

## Core state (`FocalPointAlignerCore`)

- `image_files: list[Path]` — ordered list that defines export order. **Order lives here; files on disk stay alphabetical.**
- `focal_points: dict[int, tuple]` — index → `(fx, fy)`.
- `completed: set[int]`, `auto_center_flags: dict`, `image_dimensions: dict`, `preview_dirty: set[int]`.
- `discarded: set[str]` — filenames of discarded images.
- `current_idx: int`.
- `json_path` = `<output_folder>/focal_points.json`.

### Persistence (`focal_points.json`)

- Focal data is keyed by **filename** (so it survives reordering/restart), with `focal_x`, `focal_y`, `original_width/height`, `auto_center`, `timestamp`.
- Top-level keys used by the app: `discarded` (filenames), `order` (current arrange order as filenames — added for order persistence), `current_idx`, `alignment_mode`, `preview_state`, `_meta`.
- **`load_focal_points()`** re-applies the saved `order` via `_reorder_files_by_names()` (remaps all index dicts by filename).
- Preview folders are `<input_folder>_preview_landscape` / `_preview_portrait`, files named `{idx:04d}.jpg` keyed to `image_files` position — they must be renumbered after any discard/reorder (see `discard_current`, `apply_arrange_order`).
- `config.json` at project root holds opener prefs (`last_input_dir`, `last_output_dir`, `target_width/height`, plus batch `mode` and `last_batch_root_dir`). Gitignored.

## Key invariants — read before touching the Arrange/reorder code

1. **`_display_order` must stay in sync with the core image set.**
   `ArrangeGridWidget._display_order` maps display position → `image_files` index. It is a *transient UI order*: the arrange order only reaches the core when `apply_arrange_order()` is called (manual **Save Order**, or auto-save on tab-leave / before export).
   Whenever the core image set/order changes, call `grid.sync_from_core()` (resets `_display_order` to identity and rebuilds). Currently wired in:
   - `ui/aligner_screen.py` `_on_discard` (after `discard_current`),
   - `_on_tab_changed` when entering the Arrange tab,
   - `_on_dots_moved` / `_on_shift` (nav-dot drag + `[`/`]` reorders).
2. **Export order == `image_files` order.** `end_menu.on_export` loops `image_files` and writes `{i:04d}.jpg`; slot `i` is `image_files[i]` with `focal_points[i]`.
3. **`apply_arrange_order(order)`** requires `len(order) == len(image_files)` and returns `False` on mismatch (silent save failure was a past bug — the UI now warns and re-syncs).
4. **Discards physically move files** into `<input_folder>/discarded/` and re-scan, shifting all index dicts. `image_files` indexing is compacted (no gaps).

## Focal-point setting (Original tab, mouse)

- Left single-click = set pending focal point; Left double-click = save + advance.
- Right click = set center pending; Right double-click = center + save + advance.
- Middle-click = discard.

## Keyboard shortcuts

`Enter` save+next · `Space` skip · `←→` navigate · `X` discard · `Del` clear focal · `P` preview · `O` toggle landscape/portrait · `A` Arrange tab · `[`/`]` shift order · `R` reset focal points · `F` finish/export · `Escape` finish batch (returns to opener) · `G` show position.

## Return-to-opener flow (recent behavior change)

`main.py:on_aligner_finished` now hides/closes the aligner screen and **shows the opener again** instead of quitting the app (previously it called `self.quit()`). Triggered by:
- `aligner_screen.aligner_finished` (emitted by `_on_quit` on **Escape**, and by `_on_export_complete` after export finishes),
- `aligner_screen.quit_requested` (emitted when no images remain).

`ui/end_menu.py:on_export` no longer calls `QApplication.instance().quit()`; it emits `export_complete`, which `AlignerScreen._on_export_complete` forwards as `aligner_finished`. Keep this unbroken: the EndMenu must **not** quit the app directly, or the return-to-opener flow is bypassed.

## Batch mode (root folder)

- Opener `mode` toggle (`"single"`/`"batch"`, persisted in `config.json`) switches between the single-folder stack page and the batch page. `opener.batch_started(dict)` → `main.on_batch_started`.
- `main.py` auto-advance: `on_aligner_finished` in batch mode calls `_open_next_batch_folder()` instead of showing the opener. `BatchManager.next_pending()` returns the first sub-folder whose `<sub>_aligned` output **does not** contain images.
- **Do not loop on escaped batches:** `main.py:on_batch_started` resets `_batch_seen`; `_open_next_batch_folder` skips folders already opened this session and skips done folders. Escaping without exporting leaves a folder "pending", so the next `Start Batch` resumes it (focal data survives in that folder's `<output_folder>/focal_points.json`).
- Batch config in `main._open_next_batch_folder` always sets `output_folder` to `<root>/<sub>_aligned` so done-detection and the export destination agree.
- Merge (`batch.merge_folders`) copies with `<source>_` prefix and never modifies sources; Move aligned (`batch.move_aligned_outputs`) physically moves `<sub>_aligned` folders into sibling `<root>_aligned`.

## Testing

- `tests/test_cli.py` — CLI subprocess tests (needs `cli.py` runnable with the venv Python).
- `tests/test_batch.py` — `batch.py` unit tests (discovery, done-detection, merge prefix/dedupe, move-aligned).
- `tests/test_arrange_order.py` — regression tests for discard → reorder → persist → reload, plus headless grid sync (copied regression: discarded images must vanish from the Arrange grid, arrange order must reach export and survive reload).
- `tests/test_return_to_opener.py` — return-to-opener flow AND batch auto-advance (done-based advance + escape-without-export no-loop).
- `tests/test_arrange_drag.py` — manual/print-only helper, no assertions.
- Run all: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/ -v`.
- `main.py --config <path.json>` boots straight into the aligner (skips opener) — handy for smoke tests.

## Building

`./build_macos.sh` → PyInstaller → `dist/FocalPointAligner.app` (see `FocalPointAligner.spec`).

## Conventions

- Core logic stays in `aligner_core.py` (no Qt imports there). UI lives in `ui/`.
- Keep the Arrange order/discard invariants above when modifying reorder/export code.
- Git log shows a long history of brittle arrange-tab fixes; prefer `sync_from_core()`-style reconciliation over ad-hoc rebuilds.
- Debug-log generously via `from ui.logger import logger`; the log file is the primary runtime aid.