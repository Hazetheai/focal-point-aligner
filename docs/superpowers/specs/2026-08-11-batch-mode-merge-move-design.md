# Batch Mode, Merge & Move Aligned — Design Spec

Date: 2026-08-11
Status: Approved

## Problem

Aligning a large set of images currently requires selecting each folder one at a
time: finish a batch, wait for the opener, pick the next folder, repeat. Users want:

1. **Batch (root-folder) mode** — give the app a root folder containing many
   sub-folders. It automatically moves on to the next folder after one is finished
   so large amounts of images can be processed in sequence.
2. **Merge folders** — combine several folders (aligned or not) into one output,
   prefixing each file with its source folder name.
3. **Move aligned** — gather every aligned output folder into a folder named
   `<root>_aligned` positioned adjacent to the root.

## Approach

Extend the existing single-folder app (approach A, approved): a new UI-free core
module `batch.py` (same pattern as `aligner_core.py`), a Single/Batch toggle on the
opener, a merge dialog, and auto-advance wiring in `main.py`.

## Changes

### 1. New core module `batch.py` (UI-free, no Qt imports)

`BatchManager(root: Path)`:

- `discover_subfolders() -> list[Path]` — immediate sub-directories of `root`
  containing images **or** an aligned output. Excludes anything whose name ends in
  `_aligned`, `_preview_landscape`, `_preview_portrait`, or equals `discarded`.
- `is_done(sub) -> bool` — aligned output exists and contains at least one image.
  Aligned output for a sub-folder = `<root>/<sub>_aligned` (the default export
  destination used by `FocalPointAlignerCore` when `output_folder` is unset).
- `next_pending() -> Path | None` — first not-done folder (sorted).
- `build_queue() -> list[dict]` — `{name, path, output, done}` per sub-folder.
- `merge_folders(sources: list[Path], dest: Path, use_aligned=True) -> dict` —
  per source folder: if it has an aligned output and `use_aligned`, copy the
  aligned images; otherwise copy the raw images. Each copied file is renamed to
  `<source_folder_name>_<filename>`. Collisions get a numeric suffix. Returns a
  report `{merged_count, skipped, warnings, dest}`.
- `move_aligned_outputs(root: Path) -> dict` — create sibling folder
  `<root>_aligned` (i.e. `root.parent / f"{root.name}_aligned"`), move each
  `<sub>_aligned` folder found under `root` into it (keeping the sub-folder name),
  including its `focal_points.json`. Returns `{moved: [paths], dest}`.

Shared image-extension set: `{'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}` —
reuse the same set used elsewhere (an inline constant is fine; no dependency on
`aligner_core`).

### 2. `ui/opener_screen.py` — mode toggle + batch controls

- New **Single / Batch** mode selector (persisted in `config.json` as
  `mode` = `"single"` / `"batch"`, plus `last_batch_root_dir`).
- Single mode: existing UI unchanged, plus a **Merge…** button.
- Batch mode: root-folder picker, sub-folder list (`QListWidget`) with status text
  (`✅ done` / `pending`), and buttons: **Start/Resume**, **Refresh**,
  **Merge selected…**, **Move aligned to `<root>_aligned`**.
- Emits existing `start_clicked(dict)` for single mode. For batch mode emits
  `batch_started(dict)` with `{'root': str(root), 'target_width', 'target_height'}`.
- Batch-list state resets/refreshes via `set_batch_queue(queue: list[dict])` and a
  `show_batch_all_done()` helper.

### 3. `ui/merge_dialog.py` (new)

`MergeDialog(sources: list[Path], parent) -> QDialog`:

- Source list (multi-select, pre-filled with the batch selection or editable via
  Add/Remove).
- Output-folder field (default `<first source parent>/merged`).
- "Include aligned outputs when present" checkbox (default on).
- **Merge** runs the merge (copies with prefix), shows a report with the dest path
  and any warnings, then emits `merge_complete(dict)`.
- Emits `merge_complete` signal carrying the merge report.

### 4. `main.py` — batch wiring

- Add `self.batch_mode: bool`, `self.batch_root: Path | None`,
  `self.batch_manager` to the app.
- `on_batch_started(config)` (connected from opener's `batch_started`): hide opener,
  set batch state, `_open_next_batch_folder()`.
- `_open_next_batch_folder()`: ask `batch_manager.next_pending()`; if found, create
  `AlignerScreen({...input_folder, output_folder, target_width/height})` and connect
  `aligner_finished`/`quit_requested` to `on_aligner_finished`; if none, refresh the
  opener's batch list into the "All batches complete" state and show opener.
- `on_aligner_finished(stats)`: **if batch mode**, tear down current aligner screen
  and call `_open_next_batch_folder()` instead of showing opener. Non-batch path is
  unchanged (returns to opener).
- Batch config always sets `output_folder` explicitly to `<root>/<sub>_aligned` so
  `is_done` detection and export destination agree.

### 5. `ui/end_menu.py`

No logic change. In batch mode the export confirmation text is unchanged; the
auto-advance already happens via `export_complete` → `aligner_finished`. (Optional
cosmetic note "The next folder will open automatically" is acceptable but not
required.)

### 6. `README.md`

Document the Batch toggle, merge, and move-aligned workflows.

## Data Flow

1. Opener (batch mode) → pick root → `BatchManager(root)` → queue rendered in list.
2. **Start/Resume** → `next_pending()` → `AlignerScreen` for that sub-folder.
3. Finish via export (`F`) or Escape → `aligner_finished` → batch path →
   `_open_next_batch_folder()`.
4. Next pending folder auto-loads (with existing focus handling); when none remain,
   opener batch list shows "All batches complete".
5. Merge: batch selection (or open Merge dialog from single mode) → copies with
   prefix → report dialog.
6. Move aligned: `move_aligned_outputs(root)` → list of moved folders shown.

## Error Handling

- Root with no usable sub-folders → info dialog; Start disabled.
- All folders already done → "All batches complete" state; Start disabled.
- Merge: destination exists → create/merge into it (report); filename collisions →
  numeric suffix; mixed target sizes between aligned sources → warning in report;
  undecodable image skipped → reported.
- Move: destination `<root>_aligned` exists → confirm + merge into it (never
  overwrite silently).
- Escape on a folder without export → folder stays "pending" (work persists in its
  `focal_points.json`); Start/Resume returns to it later.

## Testing

- `tests/test_batch.py`: discovery (skips `_aligned`/`_preview_*`/`discarded`),
  `is_done` (empty vs populated), `next_pending` ordering/skipping, merge
  prefixing + collision dedupe + aligned vs raw selection, move selects/renames
  correctly, report contents.
- Extend `tests/test_return_to_opener.py`: batch of 2 folders → finish first →
  assert second auto-opens → finish second → assert "All batches complete" state.
- Run `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/`.

## Files Modified

| File | Changes |
|------|---------|
| `batch.py` | New UI-free batch core. |
| `ui/opener_screen.py` | Single/Batch toggle, batch list + buttons, `batch_started` signal, Merge button. |
| `ui/merge_dialog.py` | New merge dialog. |
| `main.py` | Batch state, `_open_next_batch_folder`, batch-aware `on_aligner_finished`. |
| `tests/test_batch.py` | New core tests. |
| `tests/test_return_to_opener.py` | Batch auto-advance test. |
| `README.md` | Batch/merge/move docs. |