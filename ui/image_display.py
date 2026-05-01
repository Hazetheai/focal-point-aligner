"""
Image display widget for the Focal Point Aligner.
Displays image with focal point overlay and handles mouse clicks.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QLabel, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QCursor, QFont

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
    double_left_click = pyqtSignal()
    set_center_pending = pyqtSignal(float, float)
    double_center_save = pyqtSignal(float, float)
    discard_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        
        self._image = None
        self._pixmap = None
        self._original_pixmap = None
        self._focal_point = None
        self._pending_focal = None
        
        self._original_width = 0
        self._original_height = 0
        
        self._displayed_pixmap_rect = None
        
        self._last_click_time = 0
        self._last_click_button = None
        
        self.setStyleSheet("""
            ImageDisplayWidget {
                background-color: #1E1E2E;
                border: 2px solid #4D4D64;
                border-radius: 4px;
            }
        """)
    
    def set_image(self, cv_image):
        """Set the image to display (OpenCV format: BGR numpy array)."""
        logger.info(f"ImageDisplayWidget.set_image: image={'not None' if cv_image is not None else 'None'}")
        
        if cv_image is None:
            self._image = None
            self._pixmap = None
            self._original_pixmap = None
            self._displayed_pixmap_rect = None
            self.clear()
            self.setText("No Image")
            return
        
        self._image = cv_image
        
        h, w = cv_image.shape[:2]
        if h == 0 or w == 0:
            logger.warning(f"ImageDisplayWidget.set_image: Invalid image size {w}x{h}")
            return
        
        logger.info(f"ImageDisplayWidget.set_image: original image size={w}x{h}")
        
        self._original_width = w
        self._original_height = h
        
        rgb_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        rgb_h, rgb_w = rgb_image.shape[:2]
        
        qimage = QImage(rgb_image.data, rgb_w, rgb_h, rgb_w * 3, QImage.Format.Format_RGB888)
        
        self._original_pixmap = QPixmap.fromImage(qimage.copy())
        self._pixmap = self._original_pixmap
        
        logger.info(f"ImageDisplayWidget.set_image: created pixmap {self._pixmap.width()}x{self._pixmap.height()}")
        
        self._update_display()
    
    def set_fixed_size(self, width, height):
        """Set a fixed size for the display area."""
        super().setFixedSize(width, height)
        self._update_display()
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()
    
    def _update_display(self):
        """Update the displayed pixmap - maintains aspect ratio with padding."""
        if self._pixmap is None:
            return
        
        widget_w = self.width()
        widget_h = self.height()
        
        logger.info(f"ImageDisplayWidget._update_display: widget={widget_w}x{widget_h}")
        
        padding = 20
        available_width = widget_w - (padding * 2)
        available_height = widget_h - (padding * 2)
        
        logger.info(f"ImageDisplayWidget._update_display: padding={padding}, available={available_width}x{available_height}")
        
        if available_width <= 0 or available_height <= 0:
            logger.warning(f"ImageDisplayWidget._update_display: No available space")
            return
        
        orig_w = self._pixmap.width()
        orig_h = self._pixmap.height()
        
        logger.info(f"ImageDisplayWidget._update_display: original pixmap={orig_w}x{orig_h}")
        
        if orig_w == 0 or orig_h == 0:
            return
        
        scaled_pixmap = self._pixmap.scaled(available_width, available_height, 
                                            Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
        
        scaled_w = scaled_pixmap.width()
        scaled_h = scaled_pixmap.height()
        
        logger.info(f"ImageDisplayWidget._update_display: scaled pixmap={scaled_w}x{scaled_h}")
        
        self.setPixmap(scaled_pixmap)
        
        img_x = padding + (available_width - scaled_w) / 2
        img_y = padding + (available_height - scaled_h) / 2
        
        self._displayed_pixmap_rect = (int(img_x), int(img_y), scaled_w, scaled_h)
        
        logger.info(f"ImageDisplayWidget._update_display: image_rect={self._displayed_pixmap_rect}, orig={orig_w}x{orig_h}")
    
    def set_focal_point(self, x, y, is_pending=False):
        """Set the focal point to display (in original image coordinates)."""
        if is_pending:
            self._pending_focal = (float(x), float(y))
            self._focal_point = None
        else:
            self._focal_point = (float(x), float(y))
            self._pending_focal = None
        self.update()
    
    def clear_focal_point(self):
        """Clear the focal point."""
        self._focal_point = None
        self._pending_focal = None
    
    def get_click_position(self, event):
        """Convert widget click position to original image coordinates."""
        if self._pixmap is None or self._displayed_pixmap_rect is None:
            logger.warning("ImageDisplayWidget.get_click_position: pixmap or rect is None")
            return None
        
        img_x, img_y, disp_w, disp_h = self._displayed_pixmap_rect
        orig_w = self._pixmap.width()
        orig_h = self._pixmap.height()
        
        click_x = event.position().x()
        click_y = event.position().y()
        
        logger.info(f"ImageDisplayWidget.get_click_position: click=({click_x:.1f}, {click_y:.1f}), image_rect=({img_x}, {img_y}, {disp_w}, {disp_h}), original=({orig_w}, {orig_h})")
        
        local_x = click_x - img_x
        local_y = click_y - img_y
        
        logger.info(f"ImageDisplayWidget.get_click_position: local=({local_x:.1f}, {local_y:.1f})")
        
        if local_x < 0 or local_x > disp_w or local_y < 0 or local_y > disp_h:
            logger.warning(f"ImageDisplayWidget.get_click_position: Click outside image bounds")
            return None
        
        scale_x = orig_w / disp_w if disp_w > 0 else 1.0
        scale_y = orig_h / disp_h if disp_h > 0 else 1.0
        
        logger.info(f"ImageDisplayWidget.get_click_position: scale=({scale_x:.4f}, {scale_y:.4f})")
        
        result_x = local_x * scale_x
        result_y = local_y * scale_y
        
        result_x = max(0, min(orig_w - 1, result_x))
        result_y = max(0, min(orig_h - 1, result_y))
        
        logger.info(f"ImageDisplayWidget.get_click_position: result=({result_x:.1f}, {result_y:.1f})")
        
        return (result_x, result_y)
    
    def mousePressEvent(self, event):
        """Handle mouse click to set focal point."""
        logger.info(f"ImageDisplayWidget.mousePressEvent: button={event.button()}, pos=({event.position().x():.1f}, {event.position().y():.1f})")
        logger.info(f"ImageDisplayWidget.mousePressEvent: displayed_rect={self._displayed_pixmap_rect}")
        
        import time
        current_time = time.time()
        DOUBLE_CLICK_INTERVAL = 0.4
        
        button = event.button()
        
        if button == Qt.MouseButton.LeftButton:
            if self._last_click_button == Qt.MouseButton.LeftButton and \
               current_time - self._last_click_time < DOUBLE_CLICK_INTERVAL:
                logger.info("ImageDisplayWidget.mousePressEvent: Double left click detected")
                self._last_click_button = None
                self._last_click_time = 0
                self.double_left_click.emit()
            else:
                pos = self.get_click_position(event)
                logger.info(f"ImageDisplayWidget.mousePressEvent: converted position = {pos}")
                self._last_click_button = button
                self._last_click_time = current_time
                
                if pos is not None:
                    logger.info(f"ImageDisplayWidget.mousePressEvent: Emitting focal_point_clicked with ({pos[0]:.1f}, {pos[1]:.1f})")
                    self.focal_point_clicked.emit(pos[0], pos[1])
                else:
                    logger.warning("ImageDisplayWidget.mousePressEvent: Click position is None (outside image area)")
        
        elif button == Qt.MouseButton.RightButton:
            if self._last_click_button == Qt.MouseButton.RightButton and \
               current_time - self._last_click_time < DOUBLE_CLICK_INTERVAL:
                logger.info("ImageDisplayWidget.mousePressEvent: Double right click detected")
                self._last_click_button = None
                self._last_click_time = 0
                center_x = self._original_width / 2
                center_y = self._original_height / 2
                logger.info(f"ImageDisplayWidget.mousePressEvent: Emitting double_center_save with ({center_x:.1f}, {center_y:.1f})")
                self.double_center_save.emit(float(center_x), float(center_y))
            else:
                center_x = self._original_width / 2
                center_y = self._original_height / 2
                self._last_click_button = button
                self._last_click_time = current_time
                logger.info(f"ImageDisplayWidget.mousePressEvent: Emitting set_center_pending with ({center_x:.1f}, {center_y:.1f})")
                self.set_center_pending.emit(float(center_x), float(center_y))
        
        elif button == Qt.MouseButton.MiddleButton:
            logger.info("ImageDisplayWidget.mousePressEvent: Middle click detected")
            self.discard_requested.emit()
        
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
        
        orig_w = self._pixmap.width()
        orig_h = self._pixmap.height()
        
        scale_x = scaled_pixmap.width() / orig_w if orig_w > 0 else 1.0
        scale_y = scaled_pixmap.height() / orig_h if orig_h > 0 else 1.0
        
        logger.info(f"ImageDisplayWidget.paintEvent: scaled={scaled_pixmap.width()}x{scaled_pixmap.height()}, original={orig_w}x{orig_h}, scale=({scale_x:.4f}, {scale_y:.4f})")
        
        focal_to_draw = None
        color = None
        
        if self._pending_focal is not None:
            focal_to_draw = self._pending_focal
            color = QColor(255, 150, 0)
            logger.info(f"ImageDisplayWidget.paintEvent: Drawing PENDING focal at {focal_to_draw}")
        elif self._focal_point is not None:
            focal_to_draw = self._focal_point
            color = QColor(0, 255, 100)
            logger.info(f"ImageDisplayWidget.paintEvent: Drawing SAVED focal at {focal_to_draw}")
        
        if focal_to_draw is not None and color is not None:
            if self._displayed_pixmap_rect is not None:
                img_x, img_y, disp_w, disp_h = self._displayed_pixmap_rect
                
                disp_x = img_x + focal_to_draw[0] * scale_x
                disp_y = img_y + focal_to_draw[1] * scale_y
                
                logger.info(f"ImageDisplayWidget.paintEvent: Using displayed_rect=({img_x}, {img_y}, {disp_w}, {disp_h}), focal=({focal_to_draw[0]:.1f}, {focal_to_draw[1]:.1f})")
                logger.info(f"ImageDisplayWidget.paintEvent: Drawing at display=({disp_x:.1f}, {disp_y:.1f})")
            else:
                disp_x = focal_to_draw[0] * scale_x
                disp_y = focal_to_draw[1] * scale_y
                logger.warning(f"ImageDisplayWidget.paintEvent: No displayed_pixmap_rect, using fallback position ({disp_x:.1f}, {disp_y:.1f})")
            
            painter.setPen(QPen(color, 3))
            
            size = 16
            painter.drawEllipse(int(disp_x - size/2), int(disp_y - size/2), size, size)
            
            line_len = 20
            painter.drawLine(int(disp_x - line_len), int(disp_y), int(disp_x + line_len), int(disp_y))
            painter.drawLine(int(disp_x), int(disp_y - line_len), int(disp_x), int(disp_y + line_len))