# Arrange Tab Improvements — Design Spec

Date: 2026-05-19
Status: Approved

## Problem

The Arrange tab for reordering images has several gaps:
1. Orientation toggle (`O` key / `↻` button) doesn't work in Arrange mode.
2. Drag-and-drop inserts adjacent to the target rather than swapping into its position.
3. No keyboard shortcut to jump to the Arrange tab.
4. No way to open an image from Arrange into the Original tab for inspection.

## Changes

### 1. Orientation toggle works in Arrange tab

**Files:** `ui/aligner_screen.py`, `ui/arrange_grid.py`

Remove the tab guard in `_on_toggle_orientation()` so the `O` hotkey and `↻` button function when `_current_tab == 2`. When orientation changes while on the Arrange tab, update `_arrange_grid._orientation` and call `_build_grid()` to re-render with the new orientation's preview images.

**Source:**
- `aligner_screen.py:_on_toggle_orientation` — remove `if self._current_tab != 1: return`; after toggling, call `_build_grid()` if current tab is 2.

### 2. Drag-and-drop swap semantics

**File:** `ui/arrange_grid.py`

Currently `dropEvent` uses a "before"/"after" split based on whether the cursor is in the left/right half of the target thumbnail. Dropping on an image inserts it after that image.

Change to always drop at the target position. When the user drops image X onto thumbnail at display position Y, the result should be X at position Y and everything else shifts down. **Drop indicator lines** are removed so the visual shows a clean highlight rather than "before"/"after" lines.

**Source:**
- `arrange_grid.py:dropEvent` — `to_idx = target_idx` always (remove `_drop_target_position` logic).
- `arrange_grid.py:dragMoveEvent` — simplify to not distinguish before/after; just highlight the target thumbnail.
- `ArrangeThumbnailWidget.paintEvent` — remove drop indicator drawing.
- `ArrangeThumbnailWidget` — remove `set_drop_indicator` / `clear_drop_indicator` methods and the `_drop_indicator` attribute.

### 3. 'A' hotkey → Arrange tab

**File:** `ui/aligner_screen.py`

Add `self._shortcuts['arrange'] = QKeySequence("A")` in `_setup_shortcuts()` and a `Qt.Key.Key_A` branch in `keyPressEvent` that calls `self._tabs.setCurrentIndex(2)`.

### 4. Double-click thumbnail opens in Original tab

**Files:** `ui/arrange_grid.py`, `ui/aligner_screen.py`

Add `mouseDoubleClickEvent` to `ArrangeThumbnailWidget` that emits a signal. Propagate through `ArrangeGridWidget` via `open_image_requested(int)` signal. Connect in `AlignerScreen` to:
- Navigate the aligner to the image's **original index** (`_orig_idx`)
- Switch to tab 0 (Original mode)
- Call `_sync_all()` to refresh the UI

## Files Modified

| File | Changes |
|------|---------|
| `ui/arrange_grid.py` | Drop indicator removal, swap semantics, double-click signal |
| `ui/aligner_screen.py` | Orientation guard removal, 'A' hotkey, double-click connection |

## Testing

- Manual: Arrange images, toggle orientation, verify grid re-renders.
- Manual: Drag image 3 onto image 1 — it should land at position 1.
- Manual: Press 'A' — should switch to Arrange tab.
- Manual: Double-click a thumbnail in Arrange — should open that image in Original tab.
