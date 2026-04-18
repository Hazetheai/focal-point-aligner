"""
Navigation dots widget for the Focal Point Aligner.
Displays clickable dots representing images with page navigation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor, QPen, QFont

import styles


class NavigationDotsWidget(QWidget):
    """
    Widget displaying navigation dots for images.
    Supports clicking on dots to navigate to specific images.
    """
    
    dotClicked = pyqtSignal(int)
    pageClicked = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._total_dots = 0
        self._current_index = 0
        self._visible_start = 0
        self._visible_count = 21
        self._page_size = 21
        self._completed_indices = set()
        self._center_indices = set()
        
        self.setMinimumHeight(80)
        self.setMaximumHeight(80)
        self.setStyleSheet("background-color: #1E1E2E;")
        
        # Demo mode - show placeholder dots when no images loaded
        self._demo_mode = True
    
    def set_total_images(self, total):
        """Set total number of images."""
        self._total_dots = total
        self._update_visible_range()
        self.update()
    
    def set_current_index(self, idx):
        """Set the current image index."""
        self._current_index = idx
        self._update_visible_range()
        self.update()
    
    def set_completed_indices(self, completed, centers=None):
        """Set which indices have focal points and which are at center."""
        self._completed_indices = set(completed)
        self._center_indices = set(centers) if centers else set()
        self.update()
    
    def _update_visible_range(self):
        """Calculate which dots should be visible."""
        if self._total_dots == 0:
            self._visible_start = 0
            return
        
        half_local = self._visible_count // 2
        start = max(0, self._current_index - half_local)
        end = min(self._total_dots, self._current_index + half_local + 1)
        
        if end - start < self._visible_count:
            if start == 0:
                end = min(self._total_dots, self._visible_count)
            elif end == self._total_dots:
                start = max(0, self._total_dots - self._visible_count)
        
        self._visible_start = start
    
    def paintEvent(self, event):
        """Paint the navigation dots."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        available_width = self.width()
        available_height = self.height()
        
        # If no dots loaded, show demo dots
        if self._total_dots == 0:
            # Show 21 demo dots in center
            demo_dots = 21
            dot_radius = 8
            dot_gap = 30
            dots_y = available_height // 2
            
            total_width = demo_dots * dot_gap
            start_x = (available_width - total_width) // 2
            
            for i in range(demo_dots):
                x_pos = start_x + i * dot_gap + dot_gap // 2
                
                # Gray dots as demo
                painter.setBrush(QColor(100, 100, 100))
                painter.setPen(QPen(QColor(100, 100, 100), 1))
                painter.drawEllipse(x_pos - dot_radius, dots_y - dot_radius, 
                                 dot_radius * 2, dot_radius * 2)
            return
        
        # Original logic for actual dots
        dots_y = 25
        
        dot_radius = 8
        dot_gap = 30
        
        local_dots = min(self._visible_count, self._total_dots)
        total_local_width = local_dots * dot_gap
        
        separator_gap = 40
        page_dot_gap = 35
        
        total_pages = (self._total_dots + self._page_size - 1) // self._page_size
        current_page = self._current_index // self._page_size
        
        full_width = total_local_width + separator_gap + (total_pages * page_dot_gap)
        start_x = (available_width - full_width) // 2
        
        for i in range(local_dots):
            idx = self._visible_start + i
            x_pos = start_x + i * dot_gap + dot_gap // 2
            
            if idx == self._current_index:
                painter.setBrush(QColor(0, 200, 255))
                painter.setPen(QPen(QColor(0, 200, 255), 3))
                painter.drawEllipse(x_pos - dot_radius - 3, dots_y - dot_radius - 3, 
                                   (dot_radius + 3) * 2, (dot_radius + 3) * 2)
            elif idx in self._completed_indices:
                if idx in self._center_indices:
                    painter.setBrush(QColor(100, 100, 100))
                    painter.setPen(QPen(QColor(100, 100, 100), 1))
                    painter.drawEllipse(x_pos - dot_radius, dots_y - dot_radius, 
                                       dot_radius * 2, dot_radius * 2)
                    painter.setBrush(QColor(0, 255, 100))
                    painter.drawEllipse(x_pos - 3, dots_y - 3, 6, 6)
                else:
                    painter.setBrush(QColor(0, 255, 100))
                    painter.setPen(QPen(QColor(0, 255, 100), 1))
                    painter.drawEllipse(x_pos - dot_radius, dots_y - dot_radius, 
                                       dot_radius * 2, dot_radius * 2)
            else:
                painter.setBrush(QColor(100, 100, 100))
                painter.setPen(QPen(QColor(100, 100, 100), 1))
                painter.drawEllipse(x_pos - dot_radius, dots_y - dot_radius, 
                                   dot_radius * 2, dot_radius * 2)
        
        if self._visible_start > 0:
            painter.setPen(QColor(80, 80, 80))
            painter.setFont(QFont("Arial", 12))
            painter.drawText(start_x - 30, dots_y + 5, "...")
        
        local_end_x = start_x + local_dots * dot_gap
        if self._visible_start + local_dots < self._total_dots:
            painter.setPen(QColor(80, 80, 80))
            painter.setFont(QFont("Arial", 12))
            painter.drawText(local_end_x + 5, dots_y + 5, "...")
        
        page_start_x = local_end_x + separator_gap
        
        for page_num in range(total_pages):
            x_pos = page_start_x + page_num * page_dot_gap + page_dot_gap // 2
            
            if page_num == current_page:
                painter.setBrush(QColor(0, 200, 255))
                painter.setPen(QPen(QColor(0, 200, 255), 3))
                painter.drawEllipse(x_pos - dot_radius - 3, dots_y - dot_radius - 3, 
                                   (dot_radius + 3) * 2, (dot_radius + 3) * 2)
            else:
                painter.setBrush(QColor(150, 150, 150))
                painter.setPen(QPen(QColor(150, 150, 150), 1))
                painter.drawEllipse(x_pos - dot_radius, dots_y - dot_radius, 
                                   dot_radius * 2, dot_radius * 2)
    
    def mousePressEvent(self, event):
        """Handle click on dots."""
        if self._total_dots == 0:
            return
        
        available_width = self.width()
        dots_y = 25
        
        dot_radius = 8
        dot_gap = 30
        
        local_dots = min(self._visible_count, self._total_dots)
        total_local_width = local_dots * dot_gap
        
        separator_gap = 40
        page_dot_gap = 35
        
        total_pages = (self._total_dots + self._page_size - 1) // self._page_size
        current_page = self._current_index // self._page_size
        
        full_width = total_local_width + separator_gap + (total_pages * page_dot_gap)
        start_x = (available_width - full_width) // 2
        
        click_x = event.pos().x()
        click_y = event.pos().y()
        
        if abs(click_y - dots_y) <= 25:
            for i in range(local_dots):
                idx = self._visible_start + i
                x_pos = start_x + i * dot_gap + dot_gap // 2
                
                if abs(click_x - x_pos) <= 20:
                    if idx != self._current_index:
                        self.dotClicked.emit(idx)
                    return
            
            page_start_x = start_x + local_dots * dot_gap + separator_gap
            
            for page_num in range(total_pages):
                x_pos = page_start_x + page_num * page_dot_gap + page_dot_gap // 2
                
                if abs(click_x - x_pos) <= 20:
                    new_idx = page_num * self._page_size
                    if new_idx != self._current_index:
                        self.pageClicked.emit(new_idx)
                    return
    
    def minimumSizeHint(self):
        return QSize(400, 60)
    
    def sizeHint(self):
        return QSize(800, 60)