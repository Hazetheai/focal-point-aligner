"""
Image display widget for the Focal Point Aligner.
Displays image with focal point overlay and handles mouse clicks.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QCursor, QFont
from PyQt6.QtWidgets import QSizePolicy

import cv2
import numpy as np

import styles
from ui.logger import logger


class ImageDisplayWidget(QLabel):
    """
    Custom widget for displaying images with focal point overlay.
    Emits signal when user clicks to set focal point.
    """
    
    focal_point_clicked = pyqtSignal(float, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        
        self._image = None
        self._pixmap = None
        self._original_pixmap = None
        self._focal_point = None
        self._pending_focal = None
        self._display_scale = 1.0
        self._image_offset = QPointF(0, 0)
        self._original_width = 0
        self._original_height = 0
        
        self.setStyleSheet("""
            ImageDisplayWidget {
                background-color: #1E1E2E;
                border: 2px solid #4D4D64;
                border-radius: 4px;
            }
        """)
    
    def set_image(self, cv_image):
        """Set the image to display (OpenCV format: BGR numpy array)."""
        if cv_image is None:
            self._image = None
            self._pixmap = None
            self._original_pixmap = None
            self.setText("No Image")
            return
        
        self._image = cv_image
        
        h, w = cv_image.shape[:2]
        if h == 0 or w == 0:
            return
        
        self._original_width = w
        self._original_height = h
        
        rgb_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB).copy()
        qimage = QImage(rgb_image.data, w, h, w * 3, QImage.Format.Format_RGB888)
        self._original_pixmap = QPixmap.fromImage(qimage)
        self._pixmap = self._original_pixmap
        
        logger.debug(f"ImageDisplayWidget: Loaded image {w}x{h}")
        
        self._update_display()
    
    def set_fixed_size(self, width, height):
        """Set a fixed size for the display area."""
        super().setFixedSize(width, height)
        self._update_display()
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()
    
    def _update_display(self):
        """Update the displayed pixmap with proper scaling."""
        if self._pixmap is None:
            return
        
        available_width = self.width() - 4
        available_height = self.height() - 4
        
        pix_w = self._pixmap.width()
        pix_h = self._pixmap.height()
        
        if pix_w == 0 or pix_h == 0:
            return
        
        scale_w = available_width / pix_w
        scale_h = available_height / pix_h
        self._display_scale = min(scale_w, scale_h)
        
        scaled_w = int(pix_w * self._display_scale)
        scaled_h = int(pix_h * self._display_scale)
        
        scaled_pixmap = self._pixmap.scaled(scaled_w, scaled_h, 
                                            Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
        
        self._image_offset = QPointF(
            (available_width - scaled_w) / 2,
            (available_height - scaled_h) / 2
        )
        
        self.setPixmap(scaled_pixmap)
    
    def set_focal_point(self, x, y, is_pending=False):
        """Set the focal point to display (in original image coordinates)."""
        if is_pending:
            self._pending_focal = (float(x), float(y))
            self._focal_point = None
        else:
            self._focal_point = (float(x), float(y))
            self._pending_focal = None
        self.update()  # Trigger repaint to show focal point marker
    
    def clear_focal_point(self):
        """Clear the focal point."""
        self._focal_point = None
        self._pending_focal = None
    
    def get_click_position(self, event):
        """Convert widget click position to original image coordinates."""
        if self._pixmap is None or self._display_scale == 0:
            logger.warning("ImageDisplayWidget: _pixmap is None or _display_scale is 0")
            return None
        
        pix_w = self._pixmap.width()
        pix_h = self._pixmap.height()
        
        logger.debug(f"ImageDisplayWidget: Original image size={pix_w}x{pix_h}, display_scale={self._display_scale}")
        
        scaled_w = int(pix_w * self._display_scale)
        scaled_h = int(pix_h * self._display_scale)
        
        offset_x = self._image_offset.x()
        offset_y = self._image_offset.y()
        
        logger.debug(f"ImageDisplayWidget: Scaled size={scaled_w}x{scaled_h}, offset=({offset_x}, {offset_y})")
        logger.debug(f"ImageDisplayWidget: Click local=({event.position().x()}, {event.position().y()})")
        
        local_x = event.position().x() - offset_x
        local_y = event.position().y() - offset_y
        
        if local_x < 0 or local_x > scaled_w or local_y < 0 or local_y > scaled_h:
            logger.warning(f"ImageDisplayWidget: Click outside image bounds")
            return None
        
        img_x = local_x / self._display_scale
        img_y = local_y / self._display_scale
        
        img_x = max(0, min(pix_w - 1, img_x))
        img_y = max(0, min(pix_h - 1, img_y))
        
        logger.debug(f"ImageDisplayWidget: Converted to original coords=({img_x}, {img_y})")
        
        return (img_x, img_y)
    
    def mousePressEvent(self, event):
        """Handle mouse click to set focal point."""
        logger.debug(f"ImageDisplayWidget: mousePressEvent called, button={event.button()}")
        
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.get_click_position(event)
            logger.debug(f"ImageDisplayWidget: Click position = {pos}")
            
            if pos is not None:
                logger.info(f"ImageDisplayWidget: Emitting focal_point_clicked signal with ({pos[0]:.1f}, {pos[1]:.1f})")
                self.focal_point_clicked.emit(pos[0], pos[1])
            else:
                logger.warning("ImageDisplayWidget: Click position is None (outside image area)")
        
        super().mousePressEvent(event)
    
    def paintEvent(self, event):
        """Paint the image and focal point markers."""
        super().paintEvent(event)
        
        if self._pixmap is None:
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        scaled_pixmap = self.pixmap()
        if scaled_pixmap is None:
            return
        
        pixmap_rect = scaled_pixmap.rect()
        pixmap_x = pixmap_rect.x()
        pixmap_y = pixmap_rect.y()
        
        scale = self._display_scale
        
        focal_to_draw = None
        color = None
        
        if self._pending_focal is not None:
            focal_to_draw = self._pending_focal
            color = QColor(255, 150, 0)
            logger.debug(f"ImageDisplayWidget: Drawing PENDING focal at {focal_to_draw}")
        elif self._focal_point is not None:
            focal_to_draw = self._focal_point
            color = QColor(0, 255, 100)
            logger.debug(f"ImageDisplayWidget: Drawing SAVED focal at {focal_to_draw}")
        
        if focal_to_draw is not None and color is not None:
            disp_x = pixmap_x + focal_to_draw[0] * scale
            disp_y = pixmap_y + focal_to_draw[1] * scale
            
            painter.setPen(QPen(color, 3))
            
            size = 16
            painter.drawEllipse(int(disp_x - size/2), int(disp_y - size/2), size, size)
            
            line_len = 20
            painter.drawLine(int(disp_x - line_len), int(disp_y), int(disp_x + line_len), int(disp_y))
            painter.drawLine(int(disp_x), int(disp_y - line_len), int(disp_x), int(disp_y + line_len))
            
            logger.debug(f"ImageDisplayWidget: Drew focal marker at display ({disp_x:.1f}, {disp_y:.1f})")