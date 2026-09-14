# Arrange Tab Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix orientation toggle for Arrange tab, fix drag-and-drop swap semantics, add A hotkey for Arrange tab, and add double-click-to-open support.

**Architecture:** Two files change: `arrange_grid.py` (drag/drop semantics, double-click signal) and `aligner_screen.py` (orientation guard, hotkey, double-click connection). No new files needed.

**Tech Stack:** Python, PyQt6, OpenCV

---

### Task 1: Fix orientation toggle for Arrange tab

**Files:**
- Modify: `ui/aligner_screen.py:1000-1011`

- [ ] **Step 1: Remove tab guard and add Arrange tab rebuild in `_on_toggle_orientation`**

Current code:
```python
def _on_toggle_orientation(self):
    """Toggle between landscape and portrait preview in Preview mode."""
    if self._current_tab != 1:
        return

    self._preview_orientation = "portrait" if self._preview_orientation == "landscape" else "landscape"
    self.aligner.ensure_preview_for_current(self._preview_orientation)
    self._load_preview_images()

    if hasattr(self, '_arrange_grid'):
        self._arrange_grid._orientation = self._preview_orientation
```

Replace with:
```python
def _on_toggle_orientation(self):
    """Toggle between landscape and portrait preview."""
    self._preview_orientation = "portrait" if self._preview_orientation == "landscape" else "landscape"

    if self._current_tab == 1:
        self.aligner.ensure_preview_for_current(self._preview_orientation)
        self._load_preview_images()
    elif self._current_tab == 2 and hasattr(self, '_arrange_grid'):
        self._arrange_grid._orientation = self._preview_orientation
        self._arrange_grid._build_grid()

    if hasattr(self, '_arrange_grid'):
        self._arrange_grid._orientation = self._preview_orientation
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -m py_compile ui/aligner_screen.py`
Expected: No output (success)

- [ ] **Step 3: Commit**

```bash
git add ui/aligner_screen.py
git commit -m "fix: orientation toggle works in Arrange tab"
```

---

### Task 2: Fix drag-and-drop swap semantics and remove indicators

**Files:**
- Modify: `ui/arrange_grid.py:79-136` (drop indicators) and `395-446` (dropEvent), `346-386` (dragMoveEvent), `459-465` (clear indicators)

- [ ] **Step 1: Remove drop indicator methods from ArrangeThumbnailWidget**

Remove these methods from the class:
```python
    def set_drop_indicator(self, indicator):
        """Set the drop indicator state."""
        if self._drop_indicator != indicator:
            self._drop_indicator = indicator
            self.update()

    def clear_drop_indicator(self):
        """Clear the drop indicator."""
        self._drop_indicator = None
        self.update()
```

And remove the `_drop_indicator` attribute from `__init__`:
```python
        self._drop_indicator = None  # None, "before", or "after"
```

Also remove the drop indicator painting block in `paintEvent` (lines 128-135):
```python
        if self._drop_indicator:
            painter.setOpacity(1.0)
            painter.setPen(QPen(QColor(0, 255, 100), 3))

            if self._drop_indicator == "before":
                painter.drawLine(0, 2, self.width(), 2)
            elif self._drop_indicator == "after":
                painter.drawLine(0, self.height() - 2, self.width(), self.height() - 2)
```

- [ ] **Step 2: Simplify `dragMoveEvent` to just track the target**

Current full method. Replace the body to just track which thumbnail is hovered without before/after logic:
```python
    def dragMoveEvent(self, event):
        """Handle drag move - update hover target."""
        if not event.mimeData().hasText():
            return

        if not self._thumbnails:
            return

        pos = event.position().toPoint()
        target_idx = self._get_target_index(pos)

        if target_idx != self._drop_target_index:
            self._drop_target_index = target_idx

        event.acceptProposedAction()
```

- [ ] **Step 3: Simplify `dropEvent` to always place at target position**

Current `dropEvent` method. Replace with version that always uses `to_idx = target_idx`:
```python
    def dropEvent(self, event):
        """Handle drop - reorder display order in memory."""
        logger.info("[ARRANGE] dropEvent called")

        if not event.mimeData().hasText():
            logger.info("[ARRANGE] dropEvent: no mime data, returning")
            return

        source_display = int(event.mimeData().text())
        to_idx = -1
        logger.info(f"[ARRANGE] dropEvent: source_display={source_display}, _drop_target_index={self._drop_target_index}")

        try:
            if self._drop_target_index >= 0 and self._drop_target_index < len(self._thumbnails):
                target_idx = self._drop_target_index
                to_idx = target_idx

                if source_display != to_idx:
                    if source_display < to_idx:
                        to_idx = max(0, to_idx - 1)

                    logger.info(f"[ARRANGE] dropEvent: moving {source_display} to {to_idx}")

                    orig_idx = self._display_order.pop(source_display)
                    self._display_order.insert(to_idx, orig_idx)

                    logger.info(f"[ARRANGE] new display order: {self._display_order[:5]}...")
        except RuntimeError as e:
            logger.error(f"[ARRANGE] dropEvent RuntimeError: {e}")
            to_idx = -1
        except Exception as e:
            logger.error(f"[ARRANGE] dropEvent Exception: {type(e).__name__}: {e}")
            to_idx = -1

        logger.info(f"[ARRANGE] dropEvent: resetting state")
        self._drop_target_index = -1
        self._drag_source_index = -1
        self._drag_in_progress = False

        if to_idx >= 0:
            logger.info(f"[ARRANGE] dropEvent: rebuilding grid")
            self._build_grid()

        event.acceptProposedAction()
```

- [ ] **Step 4: Remove `_clear_all_indicators` calls from `dragLeaveEvent`**

In `dragLeaveEvent`, replace:
```python
    def dragLeaveEvent(self, event):
        """Clear state on drag leave."""
        self._drop_target_index = -1
        self._drag_in_progress = False
```

- [ ] **Step 5: Verify syntax**

Run: `python3 -m py_compile ui/arrange_grid.py`
Expected: No output (success)

- [ ] **Step 6: Commit**

```bash
git add ui/arrange_grid.py
git commit -m "fix: drag-drop now swaps in place and removes drop indicators"
```

---

### Task 3: Add 'A' hotkey for Arrange tab

**Files:**
- Modify: `ui/aligner_screen.py:411-431` (_setup_shortcuts) and `432-469` (keyPressEvent)

- [ ] **Step 1: Add 'A' shortcut in `_setup_shortcuts`**

Add after `self._shortcuts['position'] = QKeySequence("G")`:
```python
        self._shortcuts['arrange'] = QKeySequence("A")
```

- [ ] **Step 2: Add 'A' key handler in `keyPressEvent`**

Add after the `elif key == Qt.Key.Key_G:` block:
```python
        elif key == Qt.Key.Key_A:
            self._tabs.setCurrentIndex(2)
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile ui/aligner_screen.py`
Expected: No output (success)

- [ ] **Step 4: Commit**

```bash
git add ui/aligner_screen.py
git commit -m "feat: add A hotkey to switch to Arrange tab"
```

---

### Task 4: Add double-click to open image in Original tab

**Files:**
- Modify: `ui/arrange_grid.py:22-28` (signal on ArrangeThumbnailWidget), `186-214` (new signal on ArrangeGridWidget)
- Modify: `ui/aligner_screen.py` (connection)

- [ ] **Step 1: Remove old `images_reordered` signal from ArrangeGridWidget**

The `images_reordered` signal is no longer used since we use in-memory display order. Remove it from the class:
```python
    images_reordered = pyqtSignal(int, int)  # from_index, to_index
```

And remove the connection in `_create_arrange_content` (aligner_screen.py line 155):
```python
        self._arrange_grid.images_reordered.connect(self._on_arrange_reorder)
```

And remove the `_on_arrange_reorder` method entirely (aligner_screen.py lines 164-174).

- [ ] **Step 2: Add double-click signal to ArrangeGridWidget**

Add to `ArrangeGridWidget`:
```python
    open_image_requested = pyqtSignal(int)  # original index
```

- [ ] **Step 3: Add double-click handler to ArrangeThumbnailWidget**

Add method to `ArrangeThumbnailWidget`:
```python
    def mouseDoubleClickEvent(self, event):
        """Double-click to request opening this image in Original tab."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.parent().open_image_requested.emit(self._orig_idx)
        super().mouseDoubleClickEvent(event)
```

- [ ] **Step 4: Connect signal in AlignerScreen**

In `_create_arrange_content`, add after `images_reordered` connection removal:
```python
        self._arrange_grid.open_image_requested.connect(self._on_arrange_open_image)
```

Add handler method to `AlignerScreen`:
```python
    def _on_arrange_open_image(self, orig_idx):
        """Open an image from Arrange tab in Original tab."""
        logger.info(f"[ARRANGE] Opening image index {orig_idx} in Original tab")
        self.aligner.navigate_to(orig_idx)
        self._tabs.setCurrentIndex(0)
```

- [ ] **Step 5: Verify syntax**

Run: `python3 -m py_compile ui/arrange_grid.py && python3 -m py_compile ui/aligner_screen.py`
Expected: No output (success)

- [ ] **Step 6: Commit**

```bash
git add ui/arrange_grid.py ui/aligner_screen.py
git commit -m "feat: double-click arrange thumbnail opens in Original tab"
```
