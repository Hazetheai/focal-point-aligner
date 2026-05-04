"""
Arrange grid widget for the Focal Point Aligner.
Displays all images in a draggable grid for manual reordering.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QWidget, QGridLayout, QScrollArea, QFrame, QLabel
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QMimeData, QTimer
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QDrag, QCursor

import cv2
import numpy as np

import styles
from ui.logger import logger


class ArrangeThumbnailWidget(QWidget):
    """Single thumbnail in the arrange grid with focal point overlay."""
    
    def __init__(self, index, cv_image, focal_x, focal_y, min_size=100, parent=None):
        super().__init__(parent)
        self.index = index
        self._cv_image = cv_image
        self._focal_x = focal_x
        self._focal_y = focal_y
        self._min_size = min_size
        
        self._pixmap = None
        self._scaled_pixmap = None
        self._orig_w = 0
        self._orig_h = 0
        
        self._drop_indicator = None  # None, "before", or "after"
        self._is_dragging = False
        self._is_being_dragged = False
        
        self._create_pixmap()
        self.setFixedSize(min_size, min_size)
        
        self.setStyleSheet("""
            ArrangeThumbnailWidget {
                background-color: #2D2D44;
                border: 1px solid #4D4D64;
            }
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
    
    def set_drop_indicator(self, indicator):
        """Set the drop indicator state."""
        if self._drop_indicator != indicator:
            self._drop_indicator = indicator
            self.update()
    
    def clear_drop_indicator(self):
        """Clear the drop indicator."""
        self._drop_indicator = None
        self.update()
    
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
            painter.fillRect(self.rect(), QColor(45, 45, 68))
            painter.setPen(QColor(112, 112, 128))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{self.index}")
            return
        
        pw = self._scaled_pixmap.width()
        ph = self._scaled_pixmap.height()
        
        x = (self.width() - pw) // 2
        y = (self.height() - ph) // 2
        
        if self._is_being_dragged:
            painter.setOpacity(0.5)
        
        painter.drawPixmap(x, y, self._scaled_pixmap)
        
        if self._focal_x is not None and self._focal_y is not None:
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
            
            if self._drop_indicator == "before":
                painter.drawLine(0, 2, self.width(), 2)
            elif self._drop_indicator == "after":
                painter.drawLine(0, self.height() - 2, self.width(), self.height() - 2)
    
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
        """Reset drag state."""
        self._is_dragging = False
        super().mouseReleaseEvent(event)
    
    def _start_drag(self):
        """Start the drag operation."""
        logger.info(f"[ARRANGE] _start_drag called for index {self.index}")
        
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
    
    images_reordered = pyqtSignal(int, int)  # from_index, to_index
    
    def __init__(self, aligner, orientation="landscape", min_size=100, gap=8, parent=None):
        super().__init__(parent)
        self.aligner = aligner
        self._orientation = orientation
        self._min_size = min_size
        self._gap = gap
        
        self._thumbnails = []
        self._layout = QGridLayout()
        self._layout.setSpacing(gap)
        self.setLayout(self._layout)
        
        self._drag_source_index = -1
        self._drop_target_index = -1
        self._drop_target_position = None
        self._drag_in_progress = False
        self._is_building_grid = False
        
        self.setAcceptDrops(True)
        
        self._build_grid()
    
    def _build_grid(self):
        """Rebuild the grid from current image order."""
        logger.info(f"[ARRANGE] _build_grid called, _is_building_grid={self._is_building_grid}, _drag_in_progress={self._drag_in_progress}")
        
        if self._is_building_grid:
            logger.info("[ARRANGE] _build_grid: already building, returning")
            return
        
        self._is_building_grid = True
        
        logger.info(f"[ARRANGE] _build_grid: removing {self._layout.count()} widgets from layout")
        
        old_thumbnails = list(self._thumbnails)
        
        for i in reversed(range(self._layout.count())):
            item = self._layout.takeAt(i)
            if item.widget():
                item.widget().setParent(None)
        
        self._thumbnails.clear()
        
        total = len(self.aligner.image_files)
        if total == 0:
            logger.info("[ARRANGE] _build_grid: no images, returning")
            self._is_building_grid = False
            return
        
        logger.info(f"[ARRANGE] _build_grid: building {total} thumbnails")
        logger.info(f"[ARRANGE] _build_grid: image order = {[f.name[:30] for f in self.aligner.image_files[:5]]} ... {[f.name[:30] for f in self.aligner.image_files[-3:]]}")
        
        cols = self._calculate_columns()
        preview_folder = self.aligner.get_preview_folder(self._orientation)
        
        for idx in range(total):
            img = None
            preview_path = preview_folder / f"{idx:04d}.jpg"
            if preview_path.exists():
                img = cv2.imread(str(preview_path))
            if img is None:
                img = cv2.imread(str(self.aligner.image_files[idx]))
            
            focal = self.aligner.focal_points.get(idx)
            focal_x = focal[0] if focal else None
            focal_y = focal[1] if focal else None
            
            thumb = ArrangeThumbnailWidget(idx, img, focal_x, focal_y, self._min_size)
            self._thumbnails.append(thumb)
            
            col = idx % cols
            row = idx // cols
            self._layout.addWidget(thumb, row, col)
        
        self._update_grid_size()
        self._is_building_grid = False
        logger.info(f"[ARRANGE] _build_grid: complete, positions: grid[0]={self.aligner.image_files[0].name[:40] if self.aligner.image_files else 'N/A'}, grid[1]={self.aligner.image_files[1].name[:40] if len(self.aligner.image_files)>1 else 'N/A'}")
    
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
        
        old_cols = self._calculate_columns()
        self._layout.setSpacing(self._gap)
        
        for i in reversed(range(self._layout.count())):
            item = self._layout.takeAt(i)
            if item.widget():
                item.widget().deleteLater()
        
        self._thumbnails.clear()
        
        total = len(self.aligner.image_files)
        if total == 0:
            return
        
        new_cols = self._calculate_columns()
        preview_folder = self.aligner.get_preview_folder(self._orientation)
        
        for idx in range(total):
            img = None
            preview_path = preview_folder / f"{idx:04d}.jpg"
            if preview_path.exists():
                img = cv2.imread(str(preview_path))
            if img is None and idx < len(self.aligner.image_files):
                img = cv2.imread(str(self.aligner.image_files[idx]))
            
            focal = self.aligner.focal_points.get(idx)
            focal_x = focal[0] if focal else None
            focal_y = focal[1] if focal else None
            
            thumb = ArrangeThumbnailWidget(idx, img, focal_x, focal_y, self._min_size)
            self._thumbnails.append(thumb)
            
            col = idx % new_cols
            row = idx // new_cols
            self._layout.addWidget(thumb, row, col)
        
        self._update_grid_size()
    
    def dragEnterEvent(self, event):
        """Handle drag enter."""
        if event.mimeData().hasText():
            event.acceptProposedAction()
            self._drag_in_progress = True
            self._drag_source_index = int(event.mimeData().text())
    
    def dragMoveEvent(self, event):
        """Handle drag move - update drop indicators."""
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
            else:
                self._drop_target_position = None
        
        event.acceptProposedAction()
    
    def dragLeaveEvent(self, event):
        """Clear indicators on drag leave."""
        self._clear_all_indicators()
        self._drop_target_index = -1
        self._drop_target_position = None
        self._drag_in_progress = False
    
    def dropEvent(self, event):
        """Handle drop - reorder images."""
        logger.info("[ARRANGE] dropEvent called")
        
        if not event.mimeData().hasText():
            logger.info("[ARRANGE] dropEvent: no mime data, returning")
            return
        
        source_idx = int(event.mimeData().text())
        to_idx = -1
        logger.info(f"[ARRANGE] dropEvent: source_idx={source_idx}, _drop_target_index={self._drop_target_index}")
        
        try:
            if self._drop_target_index >= 0 and self._drop_target_index < len(self._thumbnails):
                target_idx = self._drop_target_index
                
                if self._drop_target_position == "before":
                    to_idx = target_idx
                else:
                    to_idx = target_idx + 1
                
                if source_idx != to_idx and source_idx != to_idx - 1:
                    to_idx = max(0, min(to_idx, len(self._thumbnails) - 1))
                    
                    if source_idx < to_idx:
                        to_idx -= 1
                    
                    logger.info(f"[ARRANGE] dropEvent: calculated to_idx={to_idx}, emitting signal")
        except RuntimeError as e:
            logger.error(f"[ARRANGE] dropEvent RuntimeError: {e}")
            to_idx = -1
        except Exception as e:
            logger.error(f"[ARRANGE] dropEvent Exception: {type(e).__name__}: {e}")
            to_idx = -1
        
        logger.info(f"[ARRANGE] dropEvent: clearing indicators")
        self._clear_all_indicators()
        self._drop_target_index = -1
        self._drop_target_position = None
        self._drag_source_index = -1
        self._drag_in_progress = False
        
        if to_idx >= 0:
            logger.info(f"[ARRANGE] dropEvent: emitting images_reordered signal for {source_idx} -> {to_idx}")
            QTimer.singleShot(0, lambda: self.images_reordered.emit(source_idx, to_idx))
        
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