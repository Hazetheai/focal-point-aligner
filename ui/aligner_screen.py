"""
Main Aligner Screen for the Focal Point Aligner.
Native PyQt6 UI replacing OpenCV-based display.
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QKeyEvent, QPixmap, QImage, QPainter, QColor, QPen, QKeySequence
from PyQt6.QtWidgets import QSizePolicy

import cv2

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import styles
from aligner_core import FocalPointAlignerCore
from ui.image_display import ImageDisplayWidget
from ui.thumbnail_widget import ThumbnailWidget
from ui.navigation_dots import NavigationDotsWidget
from ui.preview_worker import PreviewWorker
from ui.logger import logger


class AlignerScreen(QWidget):
    """
    Main PyQt6 screen for the Focal Point Aligner.
    Replaces OpenCV-based UI with native Qt widgets.
    """
    
    aligner_finished = pyqtSignal(dict)
    quit_requested = pyqtSignal()
    
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.aligner = None
        
        self._pending_focal = None
        self._current_tab = 0
        self._is_preview_mode = False
        self._landscape_preview_ready = False
        self._portrait_preview_ready = False
        self._preview_workers = []
        
        self._init_aligner()
        self._init_ui()
        # TEMPORARILY DISABLED - to test UI layout first
        # self._load_current_images()
    
    def _init_aligner(self):
        """Initialize the aligner core."""
        self.aligner = FocalPointAlignerCore(self.config)
    
    def _init_ui(self):
        """Initialize the UI components."""
        # Use 1440x1440 as default target dimensions
        target_w = self.config.get('target_width', 1440)
        target_h = self.config.get('target_height', 1440)
        
        self.setWindowTitle("Focal Point Aligner")
        self.setFixedSize(1440, 1440)  # Fixed window size
        self.setPalette(styles.get_palette())
        
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        self._create_header(layout)
        self._create_tabs(layout)
        self._create_main_area(layout)
        layout.addStretch(1)  # Makes main area stretch to fill vertical space
        self._create_navigation_dots(layout)
        self._create_footer(layout)
        
        self.setLayout(layout)
        self._setup_shortcuts()
    
    def _create_header(self, parent_layout):
        """Create the header with image info."""
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 5, 0, 5)
        
        self._image_counter_label = QLabel()
        self._image_counter_label.setStyleSheet(styles.LABEL_STYLE)
        
        self._status_label = QLabel()
        self._status_label.setStyleSheet(styles.LABEL_STYLE)
        
        self._focal_label = QLabel()
        self._focal_label.setStyleSheet(styles.LABEL_STYLE)
        
        self._completed_label = QLabel()
        self._completed_label.setStyleSheet(styles.LABEL_STYLE)
        
        header_layout.addWidget(self._image_counter_label)
        header_layout.addWidget(self._status_label)
        header_layout.addStretch()
        header_layout.addWidget(self._focal_label)
        header_layout.addWidget(self._completed_label)
        
        parent_layout.addLayout(header_layout)
    
    def _create_tabs(self, parent_layout):
        """Create the tab widget for Original/Preview modes."""
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #4D4D64;
                background-color: #1E1E2E;
            }
            QTabBar::tab {
                background-color: #2D2D44;
                color: #A0A0B0;
                padding: 10px 20px;
                border: 1px solid #4D4D64;
            }
            QTabBar::tab:selected {
                background-color: #2D5A8E;
                color: #FFFFFF;
            }
            QTabBar::tab:hover:selected {
                background-color: #3D6A9E;
            }
        """)
        
        self._original_tab = QWidget()
        self._landscape_tab = QWidget()
        self._portrait_tab = QWidget()
        
        self._tabs.addTab(self._original_tab, "Original")
        self._tabs.addTab(self._landscape_tab, "Preview - Landscape")
        self._tabs.addTab(self._portrait_tab, "Preview - Portrait")
        
        self._tabs.currentChanged.connect(self._on_tab_changed)
        
        parent_layout.addWidget(self._tabs)
    
    def _create_main_area(self, parent_layout):
        """Create the main image display area with simple placeholders."""
        main_layout = QHBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        # Previous image placeholder
        self._prev_thumbnail = QLabel("PREV\n(Image)")
        self._prev_thumbnail.setStyleSheet("""
            background-color: #2D2D44;
            color: #707080;
            border: 1px solid #4D4D64;
            border-radius: 4px;
        """)
        self._prev_thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Main image placeholder - clickable area
        self._main_image = QLabel("MAIN IMAGE AREA\n\n(Click to set focal point)")
        self._main_image.setStyleSheet("""
            background-color: #1E1E2E;
            color: #A0A0B0;
            border: 2px solid #4D4D64;
            border-radius: 4px;
        """)
        self._main_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Next image placeholder  
        self._next_thumbnail = QLabel("NEXT\n(Image)")
        self._next_thumbnail.setStyleSheet("""
            background-color: #2D2D44;
            color: #707080;
            border: 1px solid #4D4D64;
            border-radius: 4px;
        """)
        self._next_thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Equal stretch factors for three columns
        main_layout.addWidget(self._prev_thumbnail, 1)
        main_layout.addWidget(self._main_image, 1)
        main_layout.addWidget(self._next_thumbnail, 1)
        
        parent_layout.addLayout(main_layout)
    
    def _create_navigation_dots(self, parent_layout):
        """Create the navigation dots widget."""
        self._nav_dots = NavigationDotsWidget()
        self._nav_dots.setMinimumHeight(80)  # Ensure visible height
        self._nav_dots.setStyleSheet("background-color: #1E1E2E; border: 1px solid #4D4D64;")
        self._nav_dots.dotClicked.connect(self._on_dot_clicked)
        self._nav_dots.pageClicked.connect(self._on_page_clicked)
        
        parent_layout.addWidget(self._nav_dots, 0)
    
    def _create_footer(self, parent_layout):
        """Create the footer with shortcuts and progress bar."""
        footer_layout = QVBoxLayout()
        footer_layout.setSpacing(5)
        
        # Shortcuts label on top - centered
        self._shortcuts_label = QLabel("Enter: Save | Space: Skip | ←→: Navigate | P: Preview | O: Orientation | Del: Clear | X: Discard | R: Reset | ESC: Quit")
        self._shortcuts_label.setStyleSheet("color: #707080; font-size: 12px;")
        self._shortcuts_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Progress bar below
        self._progress_bar = QProgressBar()
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #2D2D44;
                border: 1px solid #4D4D64;
                border-radius: 4px;
                text-align: center;
                color: #FFFFFF;
            }
            QProgressBar::chunk {
                background-color: #2ECC71;
            }
        """)
        
        footer_layout.addWidget(self._shortcuts_label)
        footer_layout.addWidget(self._progress_bar, 1)
        
        parent_layout.addLayout(footer_layout)
    
    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        self._shortcuts = {}
        
        self._shortcuts['save'] = QKeySequence("Return")
        self._shortcuts['skip'] = QKeySequence("Space")
        self._shortcuts['prev'] = QKeySequence("Left")
        self._shortcuts['next'] = QKeySequence("Right")
        self._shortcuts['preview'] = QKeySequence("P")
        self._shortcuts['orientation'] = QKeySequence("O")
        self._shortcuts['clear'] = QKeySequence("Delete")
        self._shortcuts['discard'] = QKeySequence("X")
        self._shortcuts['reset'] = QKeySequence("R")
        self._shortcuts['quit'] = QKeySequence("Escape")
        self._shortcuts['page_back'] = QKeySequence("2")
        self._shortcuts['page_forward'] = QKeySequence("3")
        self._shortcuts['shift_left'] = QKeySequence("[")
        self._shortcuts['shift_right'] = QKeySequence("]")
        self._shortcuts['position'] = QKeySequence("G")
    
    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard shortcuts."""
        key = event.key()
        
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self._on_save_and_next()
        elif key == Qt.Key.Key_Space:
            self._on_skip()
        elif key == Qt.Key.Key_Left:
            self._on_prev()
        elif key == Qt.Key.Key_Right:
            self._on_next()
        elif key == Qt.Key.Key_P:
            self._on_toggle_preview()
        elif key == Qt.Key.Key_O:
            self._on_toggle_orientation()
        elif key == Qt.Key.Key_Delete:
            self._on_clear_focal()
        elif key == Qt.Key.Key_X:
            self._on_discard()
        elif key == Qt.Key.Key_R:
            self._on_reset_all()
        elif key == Qt.Key.Key_Escape:
            self._on_quit()
        elif key == Qt.Key.Key_2:
            self._on_page_jump(-20)
        elif key == Qt.Key.Key_3:
            self._on_page_jump(20)
        elif key == Qt.Key.Key_BracketLeft:
            self._on_shift(-1)
        elif key == Qt.Key.Key_BracketRight:
            self._on_shift(1)
        elif key == Qt.Key.Key_G:
            self._show_position()
        else:
            super().keyPressEvent(event)
    
    def _load_current_images(self):
        """Load and display current images."""
        current_img = self.aligner.get_current_image()
        if current_img is not None:
            if self._current_tab == 0:
                self._main_image.set_image(current_img)
            elif self._current_tab == 1:
                preview = self.aligner.get_preview_image("landscape")
                self._main_image.set_image(preview if preview is not None else current_img)
            else:
                preview = self.aligner.get_preview_image("portrait")
                self._main_image.set_image(preview if preview is not None else current_img)
            
            focal = self.aligner.get_current_focal()
            if focal:
                h, w = current_img.shape[:2]
                self._main_image.set_focal_point(focal[0], focal[1])
            elif self._pending_focal:
                self._main_image.set_focal_point(self._pending_focal[0], self._pending_focal[1], is_pending=True)
        
        prev_img, prev_focal = self.aligner.get_prev_image()
        if prev_img is not None:
            self._prev_thumbnail.set_image(prev_img, prev_focal is not None)
        
        next_img, next_focal = self.aligner.get_next_image()
        if next_img is not None:
            self._next_thumbnail.set_image(next_img, next_focal is not None)
        
        self._update_header()
        self._update_nav_dots()
        self._update_progress()
    
    def _update_header(self):
        """Update header labels."""
        idx = self.aligner.current_idx
        total = self.aligner.total_images
        filename = self.aligner.get_current_filename()
        
        self._image_counter_label.setText(f"IMAGE {idx + 1} / {total} | {filename}")
        
        is_completed = self.aligner.is_current_completed()
        is_center = self.aligner.is_focal_at_center()
        
        if self._pending_focal:
            self._status_label.setText("PENDING")
            self._status_label.setStyleSheet("color: #E67E22; font-size: 12px;")
        elif is_completed:
            if is_center:
                self._status_label.setText("CENTER")
                self._status_label.setStyleSheet("color: #707080; font-size: 12px;")
            else:
                self._status_label.setText("FOCAL SET")
                self._status_label.setStyleSheet("color: #2ECC71; font-size: 12px;")
        else:
            self._status_label.setText("PENDING")
            self._status_label.setStyleSheet("color: #A0A0B0; font-size: 12px;")
        
        focal = self.aligner.get_current_focal()
        if focal:
            self._focal_label.setText(f"FOCAL: ({int(focal[0])}, {int(focal[1])})")
            self._focal_label.setStyleSheet("color: #00C8C8; font-size: 12px;")
        elif self._pending_focal:
            self._focal_label.setText(f"FOCAL: ({int(self._pending_focal[0])}, {int(self._pending_focal[1])})")
            self._focal_label.setStyleSheet("color: #FF9600; font-size: 12px;")
        else:
            self._focal_label.setText("")
        
        completed = self.aligner.completed_count
        self._completed_label.setText(f"Completed: {completed} / {total}")
    
    def _update_nav_dots(self):
        """Update navigation dots."""
        self._nav_dots.set_total_images(self.aligner.total_images)
        self._nav_dots.set_current_index(self.aligner.current_idx)
        
        centers = []
        for idx in self.aligner.focal_points:
            if self.aligner.is_focal_at_center():
                centers.append(idx)
        
        self._nav_dots.set_completed_indices(self.aligner.focal_points.keys(), centers)
    
    def _update_progress(self):
        """Update progress bar."""
        total = self.aligner.total_images
        completed = self.aligner.completed_count
        pct = int((completed / total) * 100) if total > 0 else 0
        self._progress_bar.setValue(pct)
        self._progress_bar.setFormat(f"{pct}%")
    
    def _on_focal_clicked(self, x, y):
        """Handle focal point click."""
        logger.info(f"AlignerScreen: _on_focal_clicked called with ({x:.1f}, {y:.1f}), current_tab={self._current_tab}")
        
        if self._current_tab != 0:
            logger.debug("AlignerScreen: Ignoring click - not in Original tab")
            return
        
        logger.info(f"AlignerScreen: Setting pending focal point at ({x:.1f}, {y:.1f})")
        self._pending_focal = (x, y)
        self._main_image.set_focal_point(x, y, is_pending=True)
        self._update_header()
        
        logger.debug(f"AlignerScreen: Updated header, pending_focal={self._pending_focal}")
    
    def _on_tab_changed(self, index):
        """Handle tab change."""
        old_tab = self._current_tab
        self._current_tab = index
        
        if index == 0:
            self._is_preview_mode = False
        else:
            self._is_preview_mode = True
            orientation = "landscape" if index == 1 else "portrait"
            
            self.aligner.set_alignment_mode(orientation)
            
            if index == 1 and not self._landscape_preview_ready:
                self._start_preview_generation("landscape")
            elif index == 2 and not self._portrait_preview_ready:
                self._start_preview_generation("portrait")
        
        self._load_current_images()
    
    def _on_dot_clicked(self, idx):
        """Handle dot click navigation."""
        self.aligner.navigate_to(idx)
        self._pending_focal = None
        self._load_current_images()
    
    def _on_page_clicked(self, idx):
        """Handle page dot click."""
        self.aligner.navigate_to(idx)
        self._pending_focal = None
        self._load_current_images()
    
    def _on_save_and_next(self):
        """Save focal and move to next image."""
        if self._pending_focal:
            self.aligner.set_focal_point(self._pending_focal[0], self._pending_focal[1])
            self._pending_focal = None
        
        was_completed = self.aligner.is_current_completed()
        self.aligner.confirm_and_save()
        
        if self._current_tab == 1 and not self._landscape_preview_ready:
            self._start_preview_generation("landscape")
        elif self._current_tab == 2 and not self._portrait_preview_ready:
            self._start_preview_generation("portrait")
        
        self._load_current_images()
    
    def _on_skip(self):
        """Skip to next image."""
        if self.aligner.navigate(1):
            self._pending_focal = None
            self._load_current_images()
    
    def _on_prev(self):
        """Navigate to previous image."""
        self.aligner.navigate(-1)
        self._pending_focal = None
        self._load_current_images()
    
    def _on_next(self):
        """Navigate to next image."""
        self.aligner.navigate(1)
        self._pending_focal = None
        self._load_current_images()
    
    def _on_toggle_preview(self):
        """Toggle preview mode."""
        if self._is_preview_mode:
            self._tabs.setCurrentIndex(0)
        else:
            self._tabs.setCurrentIndex(1)
    
    def _on_toggle_orientation(self):
        """Toggle between landscape and portrait preview."""
        if self._current_tab == 1:
            self._tabs.setCurrentIndex(2)
        elif self._current_tab == 2:
            self._tabs.setCurrentIndex(1)
    
    def _on_clear_focal(self):
        """Clear focal point for current image."""
        self.aligner.clear_focal_point()
        self._main_image.clear_focal_point()
        self._pending_focal = None
        self._load_current_images()
    
    def _on_discard(self):
        """Discard current image."""
        self.aligner.discard_current()
        self._pending_focal = None
        self._load_current_images()
    
    def _on_reset_all(self):
        """Reset all focal points."""
        self.aligner.reset_all()
        self._pending_focal = None
        self._landscape_preview_ready = False
        self._portrait_preview_ready = False
        self._load_current_images()
    
    def _on_page_jump(self, count):
        """Jump by specified count."""
        self.aligner.page_jump(count)
        self._pending_focal = None
        self._load_current_images()
    
    def _on_shift(self, direction):
        """Shift current image position."""
        if self.aligner.shift_current(direction):
            self._load_current_images()
    
    def _show_position(self):
        """Show current position."""
        idx = self.aligner.current_idx
        total = self.aligner.total_images
        print(f"Current position: {idx + 1} / {total}")
    
    def _on_quit(self):
        """Quit the aligner."""
        stats = self.aligner.get_stats()
        self.aligner_finished.emit(stats)
    
    def _start_preview_generation(self, orientation):
        """Start background preview generation."""
        worker = PreviewWorker(self.aligner, orientation)
        worker.progress.connect(self._on_preview_progress)
        worker.finished.connect(lambda orient: self._on_preview_done(orient))
        worker.error.connect(lambda err: print(f"Preview error: {err}"))
        
        worker.start()
        self._preview_workers.append(worker)
    
    def _on_preview_progress(self, current, total):
        """Handle preview generation progress."""
        pass
    
    def _on_preview_done(self, orientation):
        """Handle preview generation completion."""
        if orientation == "landscape":
            self._landscape_preview_ready = True
        else:
            self._portrait_preview_ready = True
        
        if self._current_tab != 0:
            self._load_current_images()
    
    def closeEvent(self, event):
        """Handle window close."""
        for worker in self._preview_workers:
            worker.quit()
            worker.wait()
        event.accept()