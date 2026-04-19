"""
Navigation dots widget for the Focal Point Aligner.
Displays clickable dots representing images with page navigation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QFont

import styles
import logging

# Setup logger
logger = logging.getLogger('FocalPointAligner')


class NavigationDotsWidget(QWidget):
    """
    Widget displaying navigation dots for images.
    Supports clicking on dots to navigate to specific images.
    Supports drag-and-drop to reorder images.
    """
    
    dotClicked = pyqtSignal(int)
    pageClicked = pyqtSignal(int)
    # New signal for drag-and-drop reordering
    dotsMoved = pyqtSignal(int, int)  # from_index, to_index
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._total_dots = 0
        self._current_index = 0
        self._visible_start = 0
        self._visible_count = 21
        self._page_size = 21
        self._completed_indices = set()
        self._center_indices = set()
        
        # Drag-and-drop state
        self._dragging = False
        self._drag_start_index = -1
        self._drag_current_index = -1
        self._drag_offset = 0
        self._drag_mouse_pos = None  # Store mouse position during drag
        
        self.setMinimumHeight(60)
        self.setMaximumHeight(60)
        self.setStyleSheet("background-color: #1E1E2E;")
         
        # Demo mode - show placeholder dots when no images loaded
        self._demo_mode = True
        
        # Enable mouse tracking for drag operations
        self.setMouseTracking(True)
        
        logger.debug("NavigationDotsWidget initialized")

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
            
        # Show complete pages of visible_count dots
        # Current dot position within visible window = current_index % visible_count
        page_number = self._current_index // self._visible_count
        self._visible_start = page_number * self._visible_count
        
        # Ensure we don't go beyond total dots
        if self._visible_start >= self._total_dots:
            self._visible_start = max(0, (self._total_dots - 1) // self._visible_count) * self._visible_count

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
        
        dots_y = 30
        
        dot_radius = 8
        dot_gap = 30
        
        # Calculate actual dots to show in current page (dynamic based on remaining images)
        if self._total_dots == 0:
            local_dots = self._visible_count  # For demo mode
        else:
            local_dots = min(self._visible_count, self._total_dots - self._visible_start)
        total_local_width = local_dots * dot_gap
        
        separator_gap = 40
        page_dot_gap = 35
        
        total_pages = (self._total_dots + self._page_size - 1) // self._page_size
        current_page = self._current_index // self._page_size
        
        full_width = total_local_width + separator_gap + (total_pages * page_dot_gap)
        start_x = (available_width - full_width) // 2
        
        # Draw regular dots first
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
        
        # Draw drag feedback if dragging
        if self._dragging and self._drag_start_index != -1 and self._drag_current_index != -1 and self._drag_mouse_pos:
            # Calculate position of the dragged dot
            if self._drag_start_index >= self._visible_start and \
               self._drag_start_index < self._visible_start + local_dots:
                # Dragged dot is in visible range
                i = self._drag_start_index - self._visible_start
                x_pos = start_x + i * dot_gap + dot_gap // 2
                
                # Draw the dragged dot at current mouse position with some opacity
                painter.setBrush(QColor(0, 200, 255, 180))  # Semi-transparent blue
                painter.setPen(QPen(QColor(0, 200, 255), 2))
                painter.drawEllipse(self._drag_mouse_pos.x() - self._drag_offset - dot_radius, 
                                   dots_y - dot_radius, 
                                   dot_radius * 2, dot_radius * 2)
                
                # Draw target position indicator
                target_x = start_x + (self._drag_current_index - self._visible_start) * dot_gap + dot_gap // 2
                if self._drag_current_index >= self._visible_start and \
                   self._drag_current_index < self._visible_start + local_dots:
                    # Target is in visible range
                    painter.setPen(QPen(QColor(0, 255, 100), 2, Qt.PenStyle.DashLine))
                    painter.drawLine(target_x - 15, dots_y, target_x + 15, dots_y)
                    
                    # Draw arrow heads
                    painter.drawLine(target_x - 15, dots_y, target_x - 10, dots_y - 5)
                    painter.drawLine(target_x - 15, dots_y, target_x - 10, dots_y + 5)
                    painter.drawLine(target_x + 15, dots_y, target_x + 10, dots_y - 5)
                    painter.drawLine(target_x + 15, dots_y, target_x + 10, dots_y + 5)
        
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
        dots_y = 30
        
        dot_radius = 8
        dot_gap = 30
        
        # Calculate actual dots to show in current page (dynamic based on remaining images)
        if self._total_dots == 0:
            local_dots = self._visible_count  # For demo mode
        else:
            local_dots = min(self._visible_count, self._total_dots - self._visible_start)
        total_local_width = local_dots * dot_gap
        
        separator_gap = 40
        page_dot_gap = 35
        
        # Calculate based on visible_count pages, not _page_size
        total_pages = (self._total_dots + self._visible_count - 1) // self._visible_count
        current_page = self._current_index // self._visible_count
        
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
                        logger.debug(f"Dot clicked at index {idx}")
                        self.dotClicked.emit(idx)
                    # Start drag operation
                    self._dragging = True
                    self._drag_start_index = idx
                    self._drag_current_index = idx
                    self._drag_offset = click_x - x_pos
                    self._drag_mouse_pos = event.pos()
                    logger.debug(f"Starting drag from index {idx}")
                    self.update()  # Trigger repaint to show drag feedback
                    return
            
            page_start_x = start_x + local_dots * dot_gap + separator_gap
            
            for page_num in range(total_pages):
                x_pos = page_start_x + page_num * page_dot_gap + page_dot_gap // 2
                
                if abs(click_x - x_pos) <= 20:
                    new_idx = page_num * self._visible_count
                    if new_idx != self._current_index:
                        logger.debug(f"Page clicked at index {new_idx}")
                        self.pageClicked.emit(new_idx)
                    return
    
    def mouseMoveEvent(self, event):
        """Handle mouse movement during drag."""
        if not self._dragging or self._total_dots == 0:
            return
        
        # Update stored mouse position
        self._drag_mouse_pos = event.pos()
        
        available_width = self.width()
        dots_y = 30
        
        dot_radius = 8
        dot_gap = 30
        
        # Calculate actual dots to show in current page (dynamic based on remaining images)
        if self._total_dots == 0:
            local_dots = self._visible_count  # For demo mode
        else:
            local_dots = min(self._visible_count, self._total_dots - self._visible_start)
        
        separator_gap = 40
        page_dot_gap = 35
        
        # Calculate based on visible_count pages, not _page_size
        total_pages = (self._total_dots + self._visible_count - 1) // self._visible_count
        current_page = self._current_index // self._visible_count
        
        total_local_width = local_dots * dot_gap
        full_width = total_local_width + separator_gap + (total_pages * page_dot_gap)
        start_x = (available_width - full_width) // 2
        
        click_x = event.pos().x()
        
        # Determine which dot we're hovering over
        hover_index = -1
        for i in range(local_dots):
            idx = self._visible_start + i
            x_pos = start_x + i * dot_gap + dot_gap // 2
            
            if abs(click_x - x_pos) <= dot_gap // 2:
                hover_index = idx
                break
        
        # Also check page dots
        page_start_x = start_x + local_dots * dot_gap + separator_gap
        for page_num in range(total_pages):
            x_pos = page_start_x + page_num * page_dot_gap + page_dot_gap // 2
            if abs(click_x - x_pos) <= page_dot_gap // 2:
                # This is a page dot, calculate the corresponding index
                page_index = page_num * self._visible_count
                if 0 <= page_index < self._total_dots:
                    hover_index = page_index
                break
        
        # Update current hover index if valid
        if hover_index != -1:
            if hover_index != self._drag_current_index:
                logger.debug(f"Drag hover changed from {self._drag_current_index} to {hover_index}")
                self._drag_current_index = hover_index
                self.update()  # Trigger repaint to show updated drag feedback
    
    def mouseReleaseEvent(self, event):
        """Handle mouse button release."""
        if not self._dragging:
            return
        
        logger.debug(f"Mouse released at position {event.pos()}")
        
        # Complete the drag operation
        if self._drag_start_index != -1 and self._drag_current_index != -1:
            if self._drag_start_index != self._drag_current_index:
                logger.debug(f"Emitting dotsMoved signal: {self._drag_start_index} -> {self._drag_current_index}")
                # Emit the move signal
                self.dotsMoved.emit(self._drag_start_index, self._drag_current_index)
            else:
                logger.debug("Drag started and ended at same index - no move")
        
        # Reset drag state
        self._dragging = False
        self._drag_start_index = -1
        self._drag_current_index = -1
        self._drag_mouse_pos = None
        self.update()  # Trigger repaint to remove drag feedback
    
    def leaveEvent(self, event):
        """Handle mouse leaving widget."""
        if self._dragging:
            # Cancel drag if mouse leaves widget
            self._dragging = False
            self._drag_start_index = -1
            self._drag_current_index = -1
            self.update()
        super().leaveEvent(event)

    def minimumSizeHint(self):
        return QSize(400, 60)
    
    def sizeHint(self):
        return QSize(800, 60)