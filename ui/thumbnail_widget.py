"""
Thumbnail widget for displaying prev/next images with focal point indicator.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen
from PyQt6.QtWidgets import QSizePolicy

import cv2
import numpy as np

import styles


class ThumbnailWidget(QLabel):
    """Thumbnail display for prev/next images."""
    
    def __init__(self, label_text="", parent=None):
        super().__init__(parent)
        self.label_text = label_text
        
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setStyleSheet("""
            QLabel {
                background-color: #2D2D44;
                border: 1px solid #4D4D64;
                border-radius: 4px;
            }
        """)
        
        self._pixmap = None
        self._display_scale = 1.0
        self._has_focal = False
        
        self._update_display()
    
    def set_image(self, cv_image, has_focal=False):
        """Set the thumbnail image (OpenCV format)."""
        self._has_focal = has_focal
        
        if cv_image is None:
            self._pixmap = None
            self.setText(self.label_text)
            self.setStyleSheet("""
                QLabel {
                    background-color: #232330;
                    border: 1px solid #3D3D54;
                    border-radius: 4px;
                    color: #707080;
                    font-size: 14px;
                }
            """)
            return
        
        h, w = cv_image.shape[:2]
        if h == 0 or w == 0:
            return
        
        rgb_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        qimage = QImage(rgb_image.data, w, h, w * 3, QImage.Format.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qimage)
        
        self.setStyleSheet("""
            QLabel {
                background-color: #2D2D44;
                border: 1px solid #4D4D64;
                border-radius: 4px;
            }
        """)
        
        self._update_display()
    
    def _update_display(self):
        """Update the displayed pixmap to fill the available widget space."""
        if self._pixmap is None:
            return
        
        # Use actual widget dimensions instead of fixed values
        available_width = self.width()
        available_height = self.height()
        
        if available_width <= 0 or available_height <= 0:
            return
        
        pix_w = self._pixmap.width()
        pix_h = self._pixmap.height()
        
        if pix_w == 0 or pix_h == 0:
            return
        
        scale_w = available_width / pix_w
        scale_h = available_height / pix_h
        scale = min(scale_w, scale_h)
        
        scaled_w = int(pix_w * scale)
        scaled_h = int(pix_h * scale)
        
        scaled_pixmap = self._pixmap.scaled(scaled_w, scaled_h,
                                            Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
        
        if self._has_focal:
            painter = QPainter(scaled_pixmap)
            painter.setPen(QPen(QColor(0, 255, 100), 3))
            painter.setBrush(QColor(0, 255, 100))
            cx, cy = scaled_w // 2, scaled_h // 2
            painter.drawEllipse(cx - 8, cy - 8, 16, 16)
            painter.end()
        
        self.setPixmap(scaled_pixmap)
    
    def resizeEvent(self, event):
        """Handle widget resize to update image display."""
        super().resizeEvent(event)
        self._update_display()