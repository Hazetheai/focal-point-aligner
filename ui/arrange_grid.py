"""
Arrange grid widget for the Focal Point Aligner.
Displays all images in a draggable grid for manual reordering.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QWidget, QGridLayout, QScrollArea, QFrame, QLabel, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QMimeData, QTimer
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QDrag, QCursor

import cv2
import numpy as np

import styles
from ui.logger import logger


class ArrangeThumbnailWidget(QWidget):
    """Single thumbnail in the arrange grid with focal point overlay."""
    
    def __init__(self, index, cv_image, focal_x, focal_y, min_size=100, parent=None, show_focal=True):
        super().__init__(parent)
        self.index = index
        self._cv_image = cv_image
        self._focal_x = focal_x
        self._focal_y = focal_y
        self._min_size = min_size
        self._show_focal = show_focal
        
        self._pixmap = None
        self._scaled_pixmap = None
        self._orig_w = 0
        self._orig_h = 0
        
        self._drop_indicator = False
        self._is_dragging = False
        self._is_being_dragged = False
        self._drag_started = False
        self._selected = False
        
        self._create_pixmap()
        self.setFixedSize(min_size, min_size)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        
        self.setStyleSheet(f"""
            ArrangeThumbnailWidget {{
                background-color: #2D2D44;
                border: 2px solid #4D4D64;
            }}
            ArrangeThumbnailWidget:hover {{
                border: 2px solid #00FF64;
            }}
        """)
    
    def _create_pixmap(self):
        """Create the thumbnail pixmap from the cv image."""
        if self._cv_image is None:
            return
        
        h, w = self._cv_image.shape[:2]
        self._orig_w = w
        self._orig_h = h
        
        if w == 0 or h == 0:
            return
        
        if w >= h:
            new_w = self._min_size
            new_h = int(h * (self._min_size / w))
        else:
            new_h = self._min_size
            new_w = int(w * (self._min_size / h))
        
        scaled = cv2.resize(self._cv_image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        rgb = cv2.cvtColor(scaled, cv2.COLOR_BGR2RGB)
        qimage = QImage(rgb.data, new_w, new_h, new_w * 3, QImage.Format.Format_RGB888)
        self._scaled_pixmap = QPixmap.fromImage(qimage)
    
    def paintEvent(self, event):
        """Paint the thumbnail image and focal point."""
        try:
            super().paintEvent(event)
        except RuntimeError as e:
            logger.warning(f"[ARRANGE] paintEvent RuntimeError (widget deleted): {e}")
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if self._scaled_pixmap is None:
            return
        
        pw = self._scaled_pixmap.width()
        ph = self._scaled_pixmap.height()
        
        x = (self.width() - pw) // 2
        y = (self.height() - ph) // 2
        
        if self._is_being_dragged:
            painter.setOpacity(0.5)
        
        painter.drawPixmap(x, y, self._scaled_pixmap)
        
        if self._show_focal and self._focal_x is not None and self._focal_y is not None:
            scale_x = pw / self._orig_w if self._orig_w > 0 else 0
            scale_y = ph / self._orig_h if self._orig_h > 0 else 0
            
            draw_x = x + self._focal_x * scale_x
            draw_y = y + self._focal_y * scale_y
            
            if 0 <= draw_x <= pw and 0 <= draw_y <= ph:
                painter.setOpacity(1.0 if not self._is_being_dragged else 0.5)
                painter.setBrush(QColor(0, 255, 100))
                painter.setPen(QPen(QColor(0, 255, 100), 1))
                painter.drawEllipse(int(draw_x - 4), int(draw_y - 4), 8, 8)
        
        if self._drop_indicator:
            painter.setOpacity(1.0)
            painter.setPen(QPen(QColor(0, 255, 100), 3))
            painter.drawLine(0, 2, self.width(), 2)
        
        if self._selected:
            painter.setOpacity(1.0)
            painter.setPen(QPen(QColor(52, 152, 219), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(1, 1, self.width() - 2, self.height() - 2)
    
    def set_selected(self, selected):
        """Set selection state."""
        if self._selected != selected:
            self._selected = selected
            self.update()
    
    def is_selected(self):
        """Return selection state."""
        return self._selected
    
    def set_drop_indicator(self, active):
        """Set the drop indicator state."""
        if self._drop_indicator != active:
            self._drop_indicator = active
            self.update()
    
    def clear_drop_indicator(self):
        """Clear the drop indicator."""
        self._drop_indicator = False
        self.update()
    
    def mousePressEvent(self, event):
        """Start drag operation."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle drag movement."""
        if self._is_dragging:
            delta = event.pos() - self._drag_start_pos
            if delta.manhattanLength() > 10:
                self._start_drag()
                self._is_dragging = False
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Reset drag state. Single click selects."""
        if self._is_dragging and not self._drag_started:
            parent = self.parent()
            if hasattr(parent, 'select_thumbnail'):
                parent.select_thumbnail(self.index)
        self._is_dragging = False
        self._drag_started = False
        super().mouseReleaseEvent(event)
    
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
    
    def _start_drag(self):
        """Start the drag operation."""
        logger.info(f"[ARRANGE] _start_drag called for index {self.index}")
        
        self._drag_started = True
        self._is_being_dragged = True
        self.update()
        
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(str(self.index))
        drag.setMimeData(mime_data)
        
        pixmap = self._scaled_pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(40, 40))
        
        logger.info(f"[ARRANGE] _start_drag: calling drag.exec()")
        drag.exec(Qt.DropAction.MoveAction)
        
        logger.info(f"[ARRANGE] _start_drag: drag.exec() returned")
        
        try:
            self._is_being_dragged = False
            self.update()
        except RuntimeError as e:
            logger.warning(f"[ARRANGE] _start_drag: RuntimeError after drag.exec(): {e}")


class ArrangeGridWidget(QWidget):
    """Grid of all images for manual reordering."""
    
    open_image_requested = pyqtSignal(int)  # original index (double left-click)
    preview_image_requested = pyqtSignal(int)  # original index (double right-click)
    image_selected = pyqtSignal(int)  # original index (single click)
    order_changed = pyqtSignal(list)  # new display order
    
    def __init__(self, aligner, orientation="landscape", min_size=100, gap=8, parent=None):
        super().__init__(parent)
        self.aligner = aligner
        self._orientation = orientation
        self._min_size = min_size
        self._gap = gap
        self._show_original = True
        self._image_cache = {}
        self._selected_index = -1
        
        self._thumbnails = []
        self._layout = QGridLayout()
        self._layout.setSpacing(gap)
        self.setLayout(self._layout)
        
        self._drag_source_index = -1
        self._drop_target_index = -1
        self._drag_in_progress = False
        self._is_building_grid = False
        
        self._display_order = list(range(len(self.aligner.image_files)))
        
        self.setAcceptDrops(True)
        
        self._build_grid()
    
    def get_display_order(self):
        """Return the current display order list."""
        return self._display_order
    
    def sync_from_core(self):
        """Reset the display order to the core's current image set.

        Call after discards or any core reorder so discarded images disappear
        and the grid reflects the current image_files.
        """
        logger.info(f"[ARRANGE] sync_from_core: image_files={len(self.aligner.image_files)}")
        self._display_order = list(range(len(self.aligner.image_files)))
        self.clear_cache()
        self._build_grid()
    
    def _build_grid(self):
        """Rebuild the grid from current display order."""
        logger.info(f"[ARRANGE] _build_grid called, _is_building_grid={self._is_building_grid}, _drag_in_progress={self._drag_in_progress}")
        
        if self._is_building_grid:
            logger.info("[ARRANGE] _build_grid: already building, returning")
            return
        
        self._is_building_grid = True
        try:
            logger.info(f"[ARRANGE] _build_grid: removing {self._layout.count()} widgets from layout")
            
            for i in reversed(range(self._layout.count())):
                item = self._layout.takeAt(i)
                if item.widget():
                    item.widget().setParent(None)
            
            self._thumbnails.clear()
            
            total = len(self._display_order)
            if total == 0:
                logger.info("[ARRANGE] _build_grid: no images, returning")
                return
            
            logger.info(f"[ARRANGE] _build_grid: building {total} thumbnails")
            
            cols = self._calculate_columns()
            
            for display_pos in range(total):
                orig_idx = self._display_order[display_pos]
                
                if orig_idx < 0 or orig_idx >= len(self.aligner.image_files):
                    logger.warning(f"[ARRANGE] _build_grid: skipping stale index {orig_idx} (have {len(self.aligner.image_files)} files)")
                    continue
                
                img = self._load_or_cached(orig_idx, use_preview=(not self._show_original))
                
                focal_x = None
                focal_y = None
                if self._show_original:
                    focal = self.aligner.focal_points.get(orig_idx)
                    focal_x = focal[0] if focal else None
                    focal_y = focal[1] if focal else None
                
                thumb = ArrangeThumbnailWidget(display_pos, img, focal_x, focal_y, self._min_size, show_focal=self._show_original)
                thumb._orig_idx = orig_idx
                self._thumbnails.append(thumb)
                
                col = display_pos % cols
                row = display_pos // cols
                self._layout.addWidget(thumb, row, col)
            
            self._update_grid_size()
            self._restore_selection()
            logger.info(f"[ARRANGE] _build_grid: complete")
        finally:
            self._is_building_grid = False
    
    def _restore_selection(self):
        """Restore selection after rebuild."""
        if self._selected_index >= 0:
            for i, orig_idx in enumerate(self._display_order):
                if orig_idx == self._selected_index:
                    try:
                        self._thumbnails[i].set_selected(True)
                    except IndexError:
                        pass
                    break
    
    def _calculate_columns(self):
        """Calculate columns to fit available width."""
        available = self.parent().width() if self.parent() else 800
        cols = max(1, (available - 20) // (self._min_size + self._gap))
        return cols
    
    def _update_grid_size(self):
        """Update the grid widget size based on content."""
        if not self._thumbnails:
            return
        
        cols = self._calculate_columns()
        rows = (len(self._thumbnails) + cols - 1) // cols
        
        width = cols * self._min_size + (cols - 1) * self._gap + 20
        height = rows * self._min_size + (rows - 1) * self._gap + 20
        
        self.setMinimumSize(width, height)
    
    def resizeEvent(self, event):
        """Rebuild grid on resize."""
        super().resizeEvent(event)
        if hasattr(self, '_thumbnails') and self._thumbnails:
            self._rebuild_on_resize()
    
    def _rebuild_on_resize(self):
        """Rebuild grid when columns change due to resize."""
        if self._drag_in_progress:
            return
        
        self._layout.setSpacing(self._gap)
        
        for i in reversed(range(self._layout.count())):
            item = self._layout.takeAt(i)
            if item.widget():
                item.widget().deleteLater()
        
        self._thumbnails.clear()
        
        total = len(self._display_order)
        if total == 0:
            return
        
        new_cols = self._calculate_columns()
        
        for display_pos in range(total):
            orig_idx = self._display_order[display_pos]
            
            if orig_idx < 0 or orig_idx >= len(self.aligner.image_files):
                logger.warning(f"[ARRANGE] _rebuild_on_resize: skipping stale index {orig_idx} (have {len(self.aligner.image_files)} files)")
                continue
            
            img = self._load_or_cached(orig_idx, use_preview=(not self._show_original))
            
            if self._show_original:
                focal = self.aligner.focal_points.get(orig_idx)
                focal_x = focal[0] if focal else None
                focal_y = focal[1] if focal else None
            else:
                focal_x = None
                focal_y = None
            
            thumb = ArrangeThumbnailWidget(display_pos, img, focal_x, focal_y, self._min_size, show_focal=self._show_original)
            thumb._orig_idx = orig_idx
            self._thumbnails.append(thumb)
            
            col = display_pos % new_cols
            row = display_pos // new_cols
            self._layout.addWidget(thumb, row, col)
        
        self._update_grid_size()
        self._restore_selection()
    
    def dragEnterEvent(self, event):
        """Handle drag enter."""
        if event.mimeData().hasText():
            event.acceptProposedAction()
            self._drag_in_progress = True
            self._drag_source_index = int(event.mimeData().text())
    
    def dragMoveEvent(self, event):
        """Handle drag move - show drop indicator on target."""
        if not event.mimeData().hasText():
            return
        
        if not self._thumbnails:
            return
        
        pos = event.position().toPoint()
        target_idx = self._get_target_index(pos)
        
        if target_idx != self._drop_target_index:
            self._clear_all_indicators()
            self._drop_target_index = target_idx
            
            if target_idx >= 0 and target_idx < len(self._thumbnails):
                try:
                    self._thumbnails[target_idx].set_drop_indicator(True)
                except RuntimeError:
                    pass
        
        event.acceptProposedAction()
    
    def dragLeaveEvent(self, event):
        """Clear state on drag leave."""
        self._clear_all_indicators()
        self._drop_target_index = -1
        self._drag_in_progress = False
    
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
                    logger.info(f"[ARRANGE] dropEvent: moving {source_display} to {to_idx}")

                    orig_idx = self._display_order.pop(source_display)
                    adjusted_to = to_idx if to_idx < source_display else to_idx - 1
                    self._display_order.insert(adjusted_to, orig_idx)

                    logger.info(f"[ARRANGE] new display order: {self._display_order[:5]}...")
        except RuntimeError as e:
            logger.error(f"[ARRANGE] dropEvent RuntimeError: {e}")
            to_idx = -1
        except Exception as e:
            logger.error(f"[ARRANGE] dropEvent Exception: {type(e).__name__}: {e}")
            to_idx = -1

        logger.info(f"[ARRANGE] dropEvent: resetting state")
        self._clear_all_indicators()
        self._drop_target_index = -1
        self._drag_source_index = -1
        self._drag_in_progress = False

        if to_idx >= 0:
            logger.info(f"[ARRANGE] dropEvent: rebuilding grid")
            self._build_grid()

        event.acceptProposedAction()
    
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
    
    def _clear_all_indicators(self):
        """Clear all drop indicators."""
        for thumb in self._thumbnails:
            try:
                thumb.clear_drop_indicator()
            except RuntimeError:
                pass
    
    def _load_or_cached(self, orig_idx, use_preview):
        """Load image from cache or disk."""
        if orig_idx < 0 or orig_idx >= len(self.aligner.image_files):
            logger.warning(f"[ARRANGE] _load_or_cached: index {orig_idx} out of range ({len(self.aligner.image_files)} files)")
            return None
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
    
    def clear_cache(self):
        """Clear the image cache."""
        self._image_cache = {}
    
    def set_show_original(self, show_original):
        """Toggle between original and preview display."""
        if self._show_original != show_original:
            self._show_original = show_original
            self.clear_cache()
            self._build_grid()
    
    def get_show_original(self):
        """Return current display mode."""
        return self._show_original
    
    def set_thumbnail_size(self, size):
        """Set thumbnail size and rebuild grid."""
        if self._min_size != size:
            self._min_size = size
            self.clear_cache()
            self._build_grid()
    
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
    
