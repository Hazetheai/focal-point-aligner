# Fix Arrange Tab: RuntimeError + Auto Preview Generation

## Issue 1: RuntimeError — "wrapped C/C++ object of type ArrangeThumbnailWidget has been deleted"

### Root cause analysis
```
User starts drag → source_thumb._start_drag() → drag.exec() [BLOCKS]
                                                         ↓
                                            User drops on another thumbnail
                                                         ↓
                                         dropEvent → images_reordered.emit()
                                                         ↓
                                  _on_arrange_reorder → _build_grid()
                                                         ↓
                                    deleteLater() on ALL old thumbnails (including source)
                                                         ↓
                                 drag.exec() returns → tries self._is_being_dragged = False
                                                         ↓
                                              CRASH — widget was deleted
```

The grid rebuild happens **synchronously** during `dropEvent`, which calls `deleteLater()` on all old thumbnail widgets. But the **source thumbnail is still blocked inside `drag.exec()`**. When that call finally returns, it tries to access deleted state → crash.

### Fix in `ui/arrange_grid.py`

**1. Import QTimer** (add to line 11):
```python
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QMimeData, QTimer
```

**2. Defer grid rebuild after drop** — in `dropEvent`, replace:
```python
# Remove this line (line ~374):
self.images_reordered.emit(source_idx, to_idx)

# Replace with:
if source_idx != to_idx and source_idx != to_idx - 1:
    to_idx = max(0, min(to_idx, len(self._thumbnails) - 1))
    if source_idx < to_idx:
        to_idx -= 1
    logger.info(f"ArrangeGridWidget: Moving from {source_idx} to {to_idx}")
    # Defer rebuild until drag completes
    QTimer.singleShot(0, lambda: self.images_reordered.emit(source_idx, to_idx))
```

**3. Guard against deleted widgets in drag helpers**:

Replace `_get_target_index`:
```python
def _get_target_index(self, pos):
    """Get the target thumbnail index for a position."""
    for idx, thumb in enumerate(self._thumbnails):
        try:
            rect = thumb.geometry()
            if rect.contains(pos):
                return idx
        except RuntimeError:
            continue
    return -1
```

Replace `_clear_all_indicators`:
```python
def _clear_all_indicators(self):
    """Clear all drop indicators."""
    for thumb in self._thumbnails:
        try:
            thumb.clear_drop_indicator()
        except RuntimeError:
            pass
```

**4. Guard `_start_drag` in `ArrangeThumbnailWidget`**:

After `drag.exec()` in `_start_drag`, wrap the cleanup in try/except:
```python
drag.exec(Qt.DropAction.MoveAction)

try:
    self._is_being_dragged = False
    self.update()
except RuntimeError:
    pass
```

**5. Guard `dragMoveEvent` geometry access** — the `thumb.geometry()` call can also fail on stale widgets:
```python
if target_idx >= 0 and target_idx < len(self._thumbnails):
    try:
        thumb = self._thumbnails[target_idx]
        rect = thumb.geometry()
        rel_x = pos.x() - rect.x()
        
        if rel_x < rect.width() // 2:
            thumb.set_drop_indicator("before")
            self._drop_target_position = "before"
        else:
            thumb.set_drop_indicator("after")
            self._drop_target_position = "after"
    except RuntimeError:
        self._drop_target_position = None
```

---

## Issue 2: Auto-generate previews when entering Arrange tab

### Desired behavior
When entering the Arrange tab for the first time and previews don't exist, trigger async preview generation (same modal as Preview tab), then rebuild the grid when complete.

### Fix in `ui/aligner_screen.py`

**1. Update Arrange tab handler** (around line 881):

Replace:
```python
elif index == 2:
    logger.info(f"[TAB_CHANGE] Arrange tab selected, building grid...")
    if hasattr(self, '_arrange_grid'):
        self._arrange_grid._orientation = self._preview_orientation
        self._arrange_grid._build_grid()
```

With:
```python
elif index == 2:
    logger.info(f"[TAB_CHANGE] Arrange tab selected")
    if hasattr(self, '_arrange_grid'):
        self._arrange_grid._orientation = self._preview_orientation
        
        self.aligner.verify_and_fix_preview_integrity()
        total, need_count = self.aligner.get_preview_generation_status()
        
        if need_count > 0:
            logger.info(f"[TAB_CHANGE] Arrange tab: Generating previews, need_count={need_count}")
            self._show_preview_modal(total)
            self.aligner.prepare_all_previews_async(
                progress_callback=self._on_preview_generation_progress
            )
        else:
            logger.info(f"[TAB_CHANGE] Arrange tab: Previews exist, building grid")
            self._arrange_grid._build_grid()
```

**2. Update `_on_preview_generation_complete`** (around line 817) to also rebuild the arrange grid if that tab is active:

Add at the start of the method:
```python
def _on_preview_generation_complete(self):
    if self._preview_label:
        self._preview_label.setText("All previews generated!")
    if self._preview_progress:
        self._preview_progress.setValue(self._preview_progress.maximum())
    if self._preview_current_image_label:
        self._preview_current_image_label.setText("")
    self._hide_preview_modal()
    
    if self._current_tab == 1:
        self._load_preview_images()
    elif self._current_tab == 2:
        if hasattr(self, '_arrange_grid'):
            self._arrange_grid._build_grid()
    
    self._update_nav_dots()
    self._update_header()
    self._status_label.setText("Previews ready")
    self._status_label.setStyleSheet("color: #2ECC71; font-size: 12px;")
```

This way, after preview generation completes, the correct tab's UI is updated.

---

## Summary of changes

| File | Change |
|------|--------|
| `ui/arrange_grid.py` | Import QTimer, defer grid rebuild, guard deleted widget access in 5 places |
| `ui/aligner_screen.py` | Add preview generation trigger for Arrange tab, update completion handler |
