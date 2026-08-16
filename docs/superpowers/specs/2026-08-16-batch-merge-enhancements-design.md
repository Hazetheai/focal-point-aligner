# Batch Merge Enhancements — Design

> Date: 2026-08-16
> Status: Approved (brainstormed with user)

## Problem

Three gaps in the batch/merge UX:

1. **No multi-select.** The merge dialog's folder list and the opener's batch
   list default to single-selection, so a user cannot Ctrl/Shift-select more
   than one folder to merge.
2. **No name for the merged folder.** The merge dialog has an "Output folder"
   line-edit + Browse; the user wants a simple name field for the merged
   folder.
3. **Aligned folders invisible in the batch list.** `discover_subfolders()`
   skips any folder ending in `_aligned`, so pointing the batch root at a
   folder that contains aligned outputs shows an empty list and cannot be
   merged.

## Design

### 1. Multi-select everywhere

- `ui/merge_dialog.py`: set
  `source_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)`.
- `ui/opener_screen.py`: set the same on `batch_list`, so "Merge selected…"
  passes multiple batches into the dialog.

### 2. Merged folder name

In `MergeDialog`, replace the "Output folder:" row + Browse with a
**"Merged folder name:"** `QLineEdit` (default `"merged"`). On merge:

- Compute the sources' common parent via `os.path.commonpath`
  (fallback: first source's parent on different-drive `ValueError`).
- Destination = `<common parent>/<name>`.
- Help text updated to describe naming and the `_aligned` auto-suffix below.
- `merge_folders()` in `batch.py` is unchanged.

### 3. Batch list always shows every folder

`batch.py` gains a **`discover_all_folders()`** method: every image-bearing
subfolder *including* `*_aligned` (still excluding `discarded` and
`_preview_` caches). `build_queue()` uses it for the batch **list**.

`discover_subfolders()` stays narrow (skips `_aligned`/`discarded`/`_preview_`)
and continues to drive `next_pending()` auto-advance, so already-aligned
outputs are never re-opened as batches to process. Reopening a previously
worked root queues only unaligned folders.

Status: an `*_aligned` folder in the queue reports `done=True` (it *is*
aligned output).

### 4. `_aligned` auto-suffix on all-aligned merges

In `MergeDialog._on_merge`, when **every** selected source folder is "aligned"
(i.e. its name ends in `_aligned`, or it has an aligned output containing
images), append `_aligned` to the merged folder name (unless it already ends
with `_aligned`), regardless of what the user typed.

Rationale: the merged output is itself aligned output, so it should be
recognizable as such — and consistent with how done-detection and
move-aligned treat `*_aligned` folders.

Helper lives in `batch.py` as a UI-free predicate (e.g.
`folder_is_aligned(folder) -> bool`), used by the dialog.

## Edge cases

- Merging raw-only folders → name stays as typed (no suffix).
- Merging a mix of raw and aligned → no suffix (not *all* aligned).
- Common parent across different drives → fallback to first source's parent.
- Name already ends in `_aligned` → not double-appended.

## Testing

- `tests/test_batch.py`: `discover_all_folders()` includes `*_aligned`,
  excludes `discarded`/`_preview_`; an `*_aligned` folder in the queue has
  `done=True`; existing `discover_subfolders`/`next_pending` tests stay green.
- `tests/test_batch.py` (or a new UI test): `folder_is_aligned()` predicate.
- Manual/offscreen UI check: multi-select enabled on both lists.
