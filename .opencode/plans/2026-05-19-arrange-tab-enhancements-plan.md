# Arrange Tab Enhancements — Implementation Plan

> **Goal:** Add image selection, double-right-click, preview skip, image cache, original/preview toggle, and scale slider to the Arrange tab.

**Architecture:** Changes to `ui/arrange_grid.py` (thumbnail widget + grid) and `ui/aligner_screen.py` (tab logic + toolbar). No new files.

---

### Task 1: Skip preview integrity check when previews exist

**Files:**
- Modify: `ui/aligner_screen.py:916-932`

- [ ] **Replace integrity check ordering in `_on_tab_changed`**

Current code (lines 919-932):
```python
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

Replace with:
```python
self._arrange_grid._orientation = self._preview_orientation

total, need_count = self.aligner.get_preview_generation_status()

if need_count > 0:
    self.aligner.verify_and_fix_preview_integrity()
    total, need_count = self.aligner.get_preview_generation_status()
    if need_count > 0:
        logger.info(f"[TAB_CHANGE] Arrange tab: Generating previews, need_count={need_count}")
        self._show_preview_modal(total)
        self.aligner.prepare_all_previews_async(
            progress_callback=self._on_preview_generation_progress
        )
    else:
        logger.info(f"[TAB_CHANGE] Arrange tab: Previews exist after verify, building grid")
        self._arrange_grid._build_grid()
else:
    logger.info(f"[TAB_CHANGE] Arrange tab: All previews exist, building grid")
    self._arrange_grid._build_grid()
```

- [ ] **Verify syntax**

Run: `python3 -m py_compile ui/aligner_screen.py`

---

### Task 2: Image cache in ArrangeGridWidget

**Files:**
- Modify: `ui/arrange_grid.py:197-218` (init), `224-280` (_build_grid), `286-298` (cache clear methods)

- [ ] **Add cache init and clear methods**

In `__init__`, add after `self._display_order`:
```python
        self._image_cache = {}
```

Add methods:
```python
    def clear_cache(self):
        """Clear the image cache."""
        self._image_cache = {}

    def _load_or_cached(self, orig_idx, use_preview=True):
        """Load image from cache or disk."""
        key = ('p' if use_preview else 'o', orig_idx)
        if key in self._image_cache:
            return self._image_cache[key]
        img = None
        if use_preview:
            preview_folder = self.aligner.get_preview_folder(self._orientation)
            preview_path = preview_folder / f"{orig_idx:04d}.jpg"
            if preview_path.exists():
                img = cv2.imread(str(preview_path))
        if img is None:
            img = cv2.imread(str(self.aligner.image_files[orig_idx]))
        if img is not None:
            self._image_cache[key] = img
        return img
```

- [ ] **Update `_build_grid` to use cache**

In `_build_grid`, replace:
```python
        preview_folder = self.aligner.get_preview_folder(self._orientation)
        
        for display_pos in range(total):
            orig_idx = self._display_order[display_pos]
            
            img = None
            preview_path = preview_folder / f"{orig_idx:04d}.jpg"
            if preview_path.exists():
                img = cv2.imread(str(preview_path))
            if img is None:
                img = cv2.imread(str(self.aligner.image_files[orig_idx]))
```

With:
```python
        for display_pos in range(total):
            orig_idx = self._display_order[display_pos]
            
            img = self._load_or_cached(orig_idx, use_preview=not self._show_original)
```

- [ ] **Clear cache on orientation change**

In `aligner_screen.py:_on_toggle_orientation`, after grid orientation update add:
```python
        if hasattr(self, '_arrange_grid'):
            self._arrange_grid.clear_cache()
```

And in `_on_tab_changed` for tab 2, before building grid add:
```python
        if hasattr(self, '_arrange_grid'):
            self._arrange_grid.clear_cache()
```

- [ ] **Update `_rebuild_on_resize` to use cache**

Replace the image loading section in `_rebuild_on_resize` to use `_load_or_cached`.

---

### Task 3: Image selection with blue border

**Files:**
- Modify: `ui/arrange_grid.py` (thumbnail + grid), `ui/aligner_screen.py` (tab navigation)

- [ ] **Add selection to ArrangeThumbnailWidget**

In `__init__`, add:
```python
        self._selected = False
```

Add methods:
```python
    def set_selected(self, selected):
        """Set selection state."""
        if self._selected != selected:
            self._selected = selected
            self.update()

    def is_selected(self):
        """Return selection state."""
        return self._selected
```

In `paintEvent`, add after the drop indicator block:
```python
        if self._selected:
            painter.setOpacity(1.0)
            painter.setPen(QPen(QColor(52, 152, 219), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(1, 1, self.width() - 2, self.height() - 2)
```

- [ ] **Add click detection in mouseReleaseEvent**

Add `_drag_started` flag to `__init__`:
```python
        self._drag_started = False
```

In `_start_drag`, add `self._drag_started = True` at the start.

In `mouseReleaseEvent`, add click detection:
```python
    def mouseReleaseEvent(self, event):
        """Reset drag state. Click selects."""
        if self._is_dragging and not self._drag_started:
            parent = self.parent()
            if hasattr(parent, 'select_thumbnail'):
                parent.select_thumbnail(self.index)
        self._is_dragging = False
        self._drag_started = False
        super().mouseReleaseEvent(event)
```

- [ ] **Add selection tracking to ArrangeGridWidget**

Add signal:
```python
    image_selected = pyqtSignal(int)  # original index
```

Add to `__init__`:
```python
        self._selected_index = -1
```

Add methods:
```python
    def select_thumbnail(self, display_pos):
        """Select thumbnail at display position."""
        if display_pos >= 0 and display_pos < len(self._display_order):
            orig_idx = self._display_order[display_pos]
            self._selected_index = orig_idx
            for thumb in self._thumbnails:
                thumb.set_selected(False)
            try:
                self._thumbnails[display_pos].set_selected(True)
            except IndexError:
                pass
            self.image_selected.emit(orig_idx)

    def get_selected_index(self):
        """Return the currently selected original index."""
        return self._selected_index
```

- [ ] **Navigate to selected index on tab leave**

In `aligner_screen.py:_on_tab_changed`, in the auto-save section (or after it), add:
```python
        if old_tab == 2 and index != 2:
            if hasattr(self, '_arrange_grid'):
                sel_idx = self._arrange_grid.get_selected_index()
                if sel_idx >= 0 and sel_idx < len(self.aligner.image_files):
                    self.aligner.navigate_to(sel_idx)
```

- [ ] **Connect signal**

In `_create_arrange_content`, add:
```python
        self._arrange_grid.image_selected.connect(self._on_arrange_selected)
```

Add handler:
```python
    def _on_arrange_selected(self, orig_idx):
        """Handle image selection in Arrange tab."""
        logger.info(f"[ARRANGE] Selected image index {orig_idx}")
```

---

### Task 4: Double right-click → Preview tab

**Files:**
- Modify: `ui/arrange_grid.py`, `ui/aligner_screen.py`

- [ ] **Add signal and handler**

In `ArrangeGridWidget`, add signal:
```python
    preview_image_requested = pyqtSignal(int)  # original index
```

- [ ] **Update mouseDoubleClickEvent**

Replace:
```python
    def mouseDoubleClickEvent(self, event):
        """Double-click to open this image in Original tab."""
        if event.button() == Qt.MouseButton.LeftButton:
            parent = self.parent()
            orig_idx = getattr(self, '_orig_idx', self.index)
            if hasattr(parent, 'open_image_requested'):
                parent.open_image_requested.emit(orig_idx)
        super().mouseDoubleClickEvent(event)
```

With:
```python
    def mouseDoubleClickEvent(self, event):
        """Double-click to open image in Original or Preview tab."""
        parent = self.parent()
        orig_idx = getattr(self, '_orig_idx', self.index)
        if event.button() == Qt.MouseButton.LeftButton:
            if hasattr(parent, 'open_image_requested'):
                parent.open_image_requested.emit(orig_idx)
        elif event.button() == Qt.MouseButton.RightButton:
            if hasattr(parent, 'preview_image_requested'):
                parent.preview_image_requested.emit(orig_idx)
        super().mouseDoubleClickEvent(event)
```

- [ ] **Connect in AlignerScreen**

In `_create_arrange_content`, add:
```python
        self._arrange_grid.preview_image_requested.connect(self._on_arrange_preview_image)
```

Add handler:
```python
    def _on_arrange_preview_image(self, orig_idx):
        """Open an image from Arrange tab in Preview tab."""
        logger.info(f"[ARRANGE] Opening image index {orig_idx} in Preview tab")
        self.aligner.navigate_to(orig_idx)
        self._tabs.setCurrentIndex(1)
```

---

### Task 5: Original/preview toggle + scale slider + toolbar layout

**Files:**
- Modify: `ui/arrange_grid.py`, `ui/aligner_screen.py`

- [ ] **Add `_show_original` flag to ArrangeGridWidget**

In `__init__`:
```python
        self._show_original = True
```

Add method:
```python
    def set_show_original(self, show_original):
        """Toggle between original and preview display."""
        if self._show_original != show_original:
            self._show_original = show_original
            self.clear_cache()
            self._build_grid()
    
    def get_show_original(self):
        """Return current display mode."""
        return self._show_original
```

- [ ] **Pass `show_focal` to thumbnails based on mode**

In `_build_grid`, when creating thumbnails, pass focal only in original mode:
```python
            show_focal = self._show_original and focal_x is not None
            thumb = ArrangeThumbnailWidget(display_pos, img, focal_x, focal_y, self._min_size, show_focal=show_focal)
```

Add `show_focal` parameter to `ArrangeThumbnailWidget.__init__`:
```python
    def __init__(self, index, cv_image, focal_x, focal_y, min_size=100, parent=None, show_focal=True):
```

And in paintEvent, wrap focal drawing:
```python
        if self._show_focal and self._focal_x is not None and self._focal_y is not None:
```

- [ ] **Set default `_show_focal` in ArrangeThumbnailWidget**

In `__init__`:
```python
        self._show_focal = show_focal
```

- [ ] **Add toolbar layout to Arrange tab**

In `_create_arrange_content`, change from:
```python
        self._arrange_grid = ArrangeGridWidget(self.aligner, orientation=self._preview_orientation)
        ...
        scroll.setWidget(self._arrange_grid)
        
        arrange_layout = QVBoxLayout()
        arrange_layout.setContentsMargins(5, 5, 5, 5)
        arrange_layout.addWidget(scroll)
        self._arrange_tab.setLayout(arrange_layout)
```

To:
```python
        self._arrange_grid = ArrangeGridWidget(self.aligner, orientation=self._preview_orientation)
        self._arrange_grid.open_image_requested.connect(self._on_arrange_open_image)
        self._arrange_grid.preview_image_requested.connect(self._on_arrange_preview_image)
        self._arrange_grid.image_selected.connect(self._on_arrange_selected)
        
        scroll.setWidget(self._arrange_grid)
        
        # Toolbar
        self._arrange_toggle_btn = QPushButton("Show Original")
        self._arrange_toggle_btn.setCheckable(True)
        self._arrange_toggle_btn.setChecked(True)
        self._arrange_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D44;
                color: #FFFFFF;
                border: 1px solid #4D4D64;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:checked {
                background-color: #3498DB;
            }
        """)
        self._arrange_toggle_btn.toggled.connect(self._on_arrange_toggle_view)
        
        self._arrange_slider = QSlider(Qt.Orientation.Horizontal)
        self._arrange_slider.setRange(60, 300)
        self._arrange_slider.setValue(100)
        self._arrange_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._arrange_slider.setTickInterval(20)
        self._arrange_slider.setFixedWidth(200)
        self._arrange_slider.valueChanged.connect(self._on_arrange_scale_changed)
        
        self._arrange_scale_label = QLabel("100px")
        self._arrange_scale_label.setStyleSheet("color: #A0A0B0; font-size: 12px;")
        self._arrange_scale_label.setFixedWidth(50)
        
        toolbar_layout = QHBoxLayout()
        toolbar_layout.addWidget(self._arrange_toggle_btn)
        toolbar_layout.addSpacing(20)
        toolbar_layout.addWidget(QLabel("Size:"))
        toolbar_layout.addWidget(self._arrange_slider)
        toolbar_layout.addWidget(self._arrange_scale_label)
        toolbar_layout.addStretch()
        
        arrange_layout = QVBoxLayout()
        arrange_layout.setContentsMargins(5, 5, 5, 5)
        arrange_layout.addLayout(toolbar_layout)
        arrange_layout.addWidget(scroll)
        self._arrange_tab.setLayout(arrange_layout)
```

- [ ] **Add toggle handler**

```python
    def _on_arrange_toggle_view(self, checked):
        """Toggle between original and preview view in Arrange tab."""
        logger.info(f"[ARRANGE] Toggling view: show_original={checked}")
        self._arrange_toggle_btn.setText("Show Original" if checked else "Show Preview")
        self._arrange_grid.set_show_original(checked)
```

- [ ] **Add slider handler**

```python
    def _on_arrange_scale_changed(self, value):
        """Handle thumbnail scale change."""
        self._arrange_scale_label.setText(f"{value}px")
        self._arrange_grid.set_thumbnail_size(value)
```

Add `set_thumbnail_size` to `ArrangeGridWidget`:
```python
    def set_thumbnail_size(self, size):
        """Set thumbnail size and rebuild grid."""
        if self._min_size != size:
            self._min_size = size
            self.clear_cache()
            self._build_grid()
```
