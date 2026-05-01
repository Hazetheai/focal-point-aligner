"""
Main Aligner Screen for the Focal Point Aligner.
Native PyQt6 UI replacing OpenCV-based display.
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QProgressBar, QDialog, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QMetaObject, Q_ARG
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
from ui.end_menu import EndMenu


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
        self._preview_modal = None
        self._preview_progress = None
        self._preview_label = None
        self._preview_current_image_label = None
        
        self._init_aligner()
        self._init_ui()
        self._load_current_images()
    
    def _init_aligner(self):
        """Initialize the aligner core."""
        self.aligner = FocalPointAlignerCore(self.config)
    
    def _init_ui(self):
        """Initialize the UI components."""
        target_w = self.config.get('target_width', 1440)
        target_h = self.config.get('target_height', 1440)
        
        self.setWindowTitle("Focal Point Aligner")
        
        # Get the screen geometry and size to 90% of available screen
        screen = self.screen()
        if screen:
            screen_geometry = screen.availableGeometry()
            new_width = int(screen_geometry.width() * 0.9)
            new_height = int(screen_geometry.height() * 0.9)
            self.setFixedSize(new_width, new_height)
        else:
            self.setFixedSize(1440, 1440)
        
        self.setPalette(styles.get_palette())
        
        self._preview_orientation = "landscape"
        
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        self._create_header(layout)
        self._create_tabs(layout)
        self._create_original_content()
        self._create_preview_content()
        self._create_navigation_dots(layout)
        self._create_footer(layout)
        
        self.setLayout(layout)
        self._setup_shortcuts()
        
        self._show_original_mode()
        
        self.setFocus()
    
    def _create_original_content(self):
        """Create the 3-column layout for Original mode."""
        original_layout = QHBoxLayout()
        original_layout.setSpacing(10)
        original_layout.setContentsMargins(10, 10, 10, 10)
        
        col_width = 480
        col_height = 360
        
        self._prev_thumbnail = ThumbnailWidget("START")
        self._prev_thumbnail.setFixedSize(col_width, col_height)
        
        self._main_image = ImageDisplayWidget()
        self._main_image.setFixedSize(col_width, col_height)
        self._main_image.focal_point_clicked.connect(self._on_focal_clicked)
        self._main_image.double_left_click.connect(self._on_double_click_save)
        self._main_image.set_center_pending.connect(self._on_center_pending)
        self._main_image.double_center_save.connect(self._on_double_center_save)
        self._main_image.discard_requested.connect(self._on_middle_discard)
        
        self._next_thumbnail = ThumbnailWidget("END")
        self._next_thumbnail.setFixedSize(col_width, col_height)
        
        original_layout.addWidget(self._prev_thumbnail, 0, Qt.AlignmentFlag.AlignVCenter)
        original_layout.addWidget(self._main_image, 0, Qt.AlignmentFlag.AlignVCenter)
        original_layout.addWidget(self._next_thumbnail, 0, Qt.AlignmentFlag.AlignVCenter)
        
        self._original_tab.setLayout(original_layout)
    
    def _create_preview_content(self):
        """Create the single large image layout for Preview mode."""
        preview_layout = QVBoxLayout()
        preview_layout.setSpacing(10)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        
        self._preview_image = ImageDisplayWidget()
        self._preview_image.setMinimumSize(1420, 800)
        self._preview_image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        preview_layout.addWidget(self._preview_image, 1)
        
        self._preview_tab.setLayout(preview_layout)
    
    def _show_original_mode(self):
        """Show original mode UI elements."""
        self._prev_thumbnail.show()
        self._next_thumbnail.show()
        self._main_image.show()
        self._preview_image.hide()
    
    def _show_preview_mode(self):
        """Show preview mode UI elements."""
        self._prev_thumbnail.hide()
        self._next_thumbnail.hide()
        self._main_image.hide()
        self._preview_image.show()
    
    def _create_header(self, parent_layout):
        """Create the header with image info and action buttons."""
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 5, 0, 5)
        
        # Left side - info labels
        self._image_counter_label = QLabel()
        self._image_counter_label.setStyleSheet(styles.LABEL_STYLE)
        
        self._status_label = QLabel()
        self._status_label.setStyleSheet(styles.LABEL_STYLE)
        
        header_layout.addWidget(self._image_counter_label)
        header_layout.addWidget(self._status_label)
        header_layout.addStretch()
        
        # Right side - action buttons
        self._btn_save = QPushButton("💾 Save")
        self._btn_save.setStyleSheet(styles.BUTTON_TOOLBAR)
        self._btn_save.setToolTip("Save focal point and go to next image (Enter)")
        self._btn_save.clicked.connect(self._on_save_and_next)
        
        self._btn_skip = QPushButton("⏭ Skip")
        self._btn_skip.setStyleSheet(styles.BUTTON_TOOLBAR)
        self._btn_skip.setToolTip("Skip to next image without saving (Space)")
        self._btn_skip.clicked.connect(self._on_skip)
        
        self._btn_prev = QPushButton("◀")
        self._btn_prev.setStyleSheet(styles.BUTTON_TOOLBAR)
        self._btn_prev.setToolTip("Go to previous image (Left Arrow)")
        self._btn_prev.clicked.connect(self._on_prev)
        
        self._btn_next = QPushButton("▶")
        self._btn_next.setStyleSheet(styles.BUTTON_TOOLBAR)
        self._btn_next.setToolTip("Go to next image (Right Arrow)")
        self._btn_next.clicked.connect(self._on_next)
        
        self._btn_clear = QPushButton("⌫")
        self._btn_clear.setStyleSheet(styles.BUTTON_TOOLBAR_RED)
        self._btn_clear.setToolTip("Clear focal point from current image (Delete)")
        self._btn_clear.clicked.connect(self._on_clear_focal)
        
        self._btn_discard = QPushButton("🗑")
        self._btn_discard.setStyleSheet(styles.BUTTON_TOOLBAR_RED)
        self._btn_discard.setToolTip("Remove current image from the set (X)")
        self._btn_discard.clicked.connect(self._on_discard)
        
        self._btn_reset = QPushButton("🔄")
        self._btn_reset.setStyleSheet(styles.BUTTON_TOOLBAR_BLUE)
        self._btn_reset.setToolTip("Reset all focal points (R)")
        self._btn_reset.clicked.connect(self._on_reset_all)
        
        self._btn_finish = QPushButton("✨ Finish")
        self._btn_finish.setStyleSheet(styles.BUTTON_TOOLBAR_YELLOW)
        self._btn_finish.setToolTip("Finish and export aligned images (F)")
        self._btn_finish.clicked.connect(self._on_finish)
        
        self._btn_quit = QPushButton("🚪")
        self._btn_quit.setStyleSheet(styles.BUTTON_TOOLBAR_GRAY)
        self._btn_quit.setToolTip("Quit the aligner (Escape)")
        self._btn_quit.clicked.connect(self._on_quit)
        
        # Help button
        self._btn_help = QPushButton("?")
        self._btn_help.setStyleSheet(styles.BUTTON_TOOLBAR_GRAY)
        self._btn_help.setToolTip("Show help and keyboard shortcuts")
        self._btn_help.clicked.connect(self._on_help)
        
        # Preview and orientation buttons
        self._btn_preview = QPushButton("👁")
        self._btn_preview.setStyleSheet(styles.BUTTON_TOOLBAR)
        self._btn_preview.setToolTip("Toggle preview mode (P)")
        self._btn_preview.clicked.connect(self._on_toggle_preview)
        
        self._btn_orientation = QPushButton("↻")
        self._btn_orientation.setStyleSheet(styles.BUTTON_TOOLBAR)
        self._btn_orientation.setToolTip("Toggle preview orientation (O)")
        self._btn_orientation.clicked.connect(self._on_toggle_orientation)
        
        header_layout.addWidget(self._btn_save)
        header_layout.addWidget(self._btn_skip)
        header_layout.addSpacing(10)
        header_layout.addWidget(self._btn_prev)
        header_layout.addWidget(self._btn_next)
        header_layout.addSpacing(10)
        header_layout.addWidget(self._btn_preview)
        header_layout.addWidget(self._btn_orientation)
        header_layout.addSpacing(10)
        header_layout.addWidget(self._btn_clear)
        header_layout.addWidget(self._btn_discard)
        header_layout.addWidget(self._btn_reset)
        header_layout.addSpacing(10)
        header_layout.addWidget(self._btn_finish)
        header_layout.addWidget(self._btn_help)
        header_layout.addWidget(self._btn_quit)
        
        # Add spacing before completed label would have been
        header_layout.addSpacing(15)
        
        self._focal_label = QLabel()
        self._focal_label.setStyleSheet(styles.LABEL_STYLE)
        
        self._completed_label = QLabel()
        self._completed_label.setStyleSheet(styles.LABEL_STYLE)
        
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
        self._preview_tab = QWidget()
        
        self._tabs.addTab(self._original_tab, "Original")
        self._tabs.addTab(self._preview_tab, "Preview")
        
        self._tabs.currentChanged.connect(self._on_tab_changed)
        
        parent_layout.addWidget(self._tabs)
    
    def _create_navigation_dots(self, parent_layout):
        """Create the navigation dots widget."""
        self._nav_dots = NavigationDotsWidget()
        self._nav_dots.setFixedHeight(60)
        self._nav_dots.setStyleSheet("background-color: #1E1E2E; border: 1px solid #4D4D64;")
        self._nav_dots.dotClicked.connect(self._on_dot_clicked)
        self._nav_dots.pageClicked.connect(self._on_page_clicked)
        self._nav_dots.dotsMoved.connect(self._on_dots_moved)
        
        parent_layout.addWidget(self._nav_dots, 0)
    
    def _create_footer(self, parent_layout):
        """Create the footer with shortcuts and progress bar."""
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(15)
        
        # Shortcuts label
        self._shortcuts_label = QLabel(
            "<b>⌨️ Shortcuts</b> &nbsp;&nbsp;"
            "<span style='color:#60E080;font-weight:bold;'>Enter</span> Save &nbsp;|&nbsp; "
            "<span style='color:#60E080;font-weight:bold;'>Space</span> Skip &nbsp;|&nbsp; "
            "<span style='color:#60E080;font-weight:bold;'>←→</span> Navigate &nbsp;|&nbsp; "
            "<span style='color:#60E080;font-weight:bold;'>P</span> Preview &nbsp;|&nbsp; "
            "<span style='color:#60E080;font-weight:bold;'>O</span> Orientation &nbsp;|&nbsp; "
            "<span style='color:#FF7070;font-weight:bold;'>Del</span> Clear &nbsp;|&nbsp; "
            "<span style='color:#FF7070;font-weight:bold;'>X</span> Discard &nbsp;|&nbsp; "
            "<span style='color:#7070FF;font-weight:bold;'>R</span> Reset &nbsp;|&nbsp; "
            "<span style='color:#FFFF70;font-weight:bold;'>F</span> Finish &nbsp;|&nbsp; "
            "<span style='color:#909098;'>ESC</span> Quit"
        )
        self._shortcuts_label.setStyleSheet("font-size: 14px; padding: 4px;")
        self._shortcuts_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._shortcuts_label.setFixedHeight(30)
        
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
        self._progress_bar.setFixedHeight(20)
        
        footer_layout.addWidget(self._shortcuts_label)
        footer_layout.addWidget(self._progress_bar)
        
        footer_container = QWidget()
        footer_container.setFixedHeight(60)
        footer_container.setLayout(footer_layout)
        parent_layout.addWidget(footer_container)
    
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
        self._shortcuts['finish'] = QKeySequence("F")
    
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
        elif key == Qt.Key.Key_F:
            self._on_finish()
        else:
            super().keyPressEvent(event)
    
    def _load_current_images(self):
        """Load and display current images."""
        from ui.logger import logger
        logger.info(f"_load_current_images: current_idx={self.aligner.current_idx}, tab={self._current_tab}")
        
        if self._current_tab == 0:
            self._load_original_images()
        else:
            self._load_preview_images()
        
        self._update_header()
        self._update_nav_dots()
        self._update_progress()
    
    def _sync_all(self):
        """Unified sync for all UI elements after index changes - for Original mode."""
        logger.info(f"[SYNC_ALL] START: current_idx={self.aligner.current_idx}, total_images={self.aligner.total_images}, tab={self._current_tab}, is_preview={self._is_preview_mode}")
        
        # Check for empty list
        if self.aligner.total_images == 0:
            logger.warning(f"[SYNC_ALL] No images remaining!")
            self._show_no_images_message()
            return
        
        # Switch to original tab to show thumbnails
        if self._current_tab != 0:
            logger.info(f"[SYNC_ALL] Switching from tab {self._current_tab} to 0")
            self._tabs.setCurrentIndex(0)
            self._current_tab = 0
            self._is_preview_mode = False
            self._show_original_mode()
        
        logger.info(f"[SYNC_ALL] Loading original images...")
        self._load_original_images()
        
        logger.info(f"[SYNC_ALL] Updating header...")
        self._update_header()
        
        logger.info(f"[SYNC_ALL] Updating nav dots to idx={self.aligner.current_idx}...")
        self._update_nav_dots()
        
        logger.info(f"[SYNC_ALL] Updating progress...")
        self._update_progress()
        
        logger.info(f"[SYNC_ALL] DONE: current_idx={self.aligner.current_idx}, total_images={self.aligner.total_images}")
    
    def _sync_preview(self):
        """Unified sync for preview mode after index changes."""
        logger.info(f"[SYNC_PREVIEW] START: current_idx={self.aligner.current_idx}, total_images={self.aligner.total_images}, tab={self._current_tab}")
        
        # Check for empty list
        if self.aligner.total_images == 0:
            logger.warning(f"[SYNC_PREVIEW] No images remaining!")
            self._show_no_images_message()
            return
        
        logger.info(f"[SYNC_PREVIEW] Loading preview images...")
        self._load_preview_images()
        
        logger.info(f"[SYNC_PREVIEW] Updating header...")
        self._update_header()
        
        logger.info(f"[SYNC_PREVIEW] Updating nav dots to idx={self.aligner.current_idx}...")
        self._update_nav_dots()
        
        logger.info(f"[SYNC_PREVIEW] DONE: current_idx={self.aligner.current_idx}, total_images={self.aligner.total_images}")
    
    def _show_no_images_message(self):
        """Show message when no images remain."""
        QMessageBox.information(
            self,
            "No Images",
            "No images remain in the set. Please select a new folder."
        )
        # Emit quit signal
        self.quit_requested.emit()
    
    def _load_original_images(self):
        """Load images for Original mode (3-column layout)."""
        from ui.logger import logger
        
        current_img = self.aligner.get_current_image()
        if current_img is not None:
            self._main_image.set_image(current_img)
            
            focal = self.aligner.get_current_focal()
            if focal:
                self._main_image.set_focal_point(focal[0], focal[1])
            elif self._pending_focal:
                self._main_image.set_focal_point(self._pending_focal[0], self._pending_focal[1], is_pending=True)
            else:
                self._main_image.clear_focal_point()
        
        prev_img, prev_focal = self.aligner.get_prev_image()
        logger.info(f"_load_original_images: prev_img={'not None' if prev_img is not None else 'None'}")
        if prev_img is not None:
            prev_coords = self.aligner.get_prev_focal()
            fx = prev_coords[0] if prev_coords else None
            fy = prev_coords[1] if prev_coords else None
            self._prev_thumbnail.set_image(prev_img, fx, fy)
        else:
            self._prev_thumbnail.set_image(None)
        
        next_img, next_focal = self.aligner.get_next_image()
        logger.info(f"_load_original_images: next_img={'not None' if next_img is not None else 'None'}")
        if next_img is not None:
            next_coords = self.aligner.get_next_focal()
            fx = next_coords[0] if next_coords else None
            fy = next_coords[1] if next_coords else None
            self._next_thumbnail.set_image(next_img, fx, fy)
        else:
            self._next_thumbnail.set_image(None)
    
    def _load_preview_images(self):
        """Load preview image for Preview mode (single large image)."""
        logger.info(f"[LOAD_PREVIEW] START: current_idx={self.aligner.current_idx}, total_images={self.aligner.total_images}, orientation={self._preview_orientation}")
        
        self.aligner.ensure_preview_for_current(self._preview_orientation)
        
        preview = self.aligner.get_preview_image(self._preview_orientation)
        current_img = self.aligner.get_current_image()
        
        logger.info(f"[LOAD_PREVIEW] preview={'not None' if preview is not None else 'None'}, current_img={'not None' if current_img is not None else 'None'}")
        
        if preview is not None:
            self._preview_image.set_image(preview)
        elif current_img is not None:
            self._preview_image.set_image(current_img)
        else:
            self._preview_image.set_image(None)
    
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
            if self.aligner.is_focal_at_center_idx(idx):
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
    
    def _on_double_click_save(self):
        """Handle double left click - save focal point and advance to next image."""
        logger.info("AlignerScreen: _on_double_click_save called")
        
        if self._current_tab != 0:
            return
        
        self._on_save_and_next()
    
    def _on_center_pending(self, x, y):
        """Handle right single click - set center as pending focal point."""
        logger.info(f"AlignerScreen: _on_center_pending called with ({x:.1f}, {y:.1f})")
        
        if self._current_tab != 0:
            return
        
        self._pending_focal = (x, y)
        self._main_image.set_focal_point(x, y, is_pending=True)
        self._update_header()
    
    def _on_double_center_save(self, x, y):
        """Handle right double click - set center, save and advance."""
        logger.info(f"AlignerScreen: _on_double_center_save called with ({x:.1f}, {y:.1f})")
        
        if self._current_tab != 0:
            return
        
        self._pending_focal = (x, y)
        self._main_image.set_focal_point(x, y, is_pending=True)
        self._update_header()
        self._on_save_and_next()
    
    def _on_middle_discard(self):
        """Handle middle click - discard current image."""
        logger.info("AlignerScreen: _on_middle_discard called")
        
        if self._current_tab != 0:
            return
        
        if self.aligner.total_images <= 1:
            self._show_toast("Cannot discard last image")
            return
        
        filename = self.aligner.get_current_filename()
        self._on_discard()
        self._show_toast(f"Discarded: {filename}")
    
    def _show_toast(self, message, duration=2000):
        """Show a toast notification that auto-dismisses."""
        toast = QLabel(message, self)
        toast.setStyleSheet("""
            QLabel {
                background-color: #3D3D5C;
                color: #FFFFFF;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
            }
        """)
        toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        toast.adjustSize()
        
        x = (self.width() - toast.width()) // 2
        y = self.height() - toast.height() - 50
        toast.move(x, y)
        
        toast.show()
        
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(duration, toast.deleteLater)
    
    def _show_preview_modal(self, total):
        self._preview_modal = QDialog(self)
        self._preview_modal.setWindowTitle("Generating Previews")
        self._preview_modal.setModal(True)
        self._preview_modal.setFixedSize(450, 200)
        self._preview_modal.setStyleSheet("""
            QDialog {
                background-color: rgba(30, 30, 46, 240);
            }
        """)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        title = QLabel("Generating Previews...")
        title.setStyleSheet("color: #FFFFFF; font-size: 16px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self._preview_label = QLabel(f"Preparing to generate {total} previews...")
        self._preview_label.setStyleSheet("color: #A0A0B0; font-size: 13px;")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self._preview_current_image_label = QLabel("")
        self._preview_current_image_label.setStyleSheet("color: #707080; font-size: 11px;")
        self._preview_current_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_current_image_label.setWordWrap(True)
        
        self._preview_progress = QProgressBar()
        self._preview_progress.setRange(0, total)
        self._preview_progress.setValue(0)
        self._preview_progress.setStyleSheet("""
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
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #3D3D5C;
                color: #FFFFFF;
                border: 1px solid #4D4D64;
                padding: 8px 20px;
                border-radius: 4px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #4D4D6C;
            }
        """)
        cancel_btn.clicked.connect(self._on_preview_generation_cancel)
        
        layout.addWidget(title)
        layout.addWidget(self._preview_label)
        layout.addWidget(self._preview_current_image_label)
        layout.addWidget(self._preview_progress)
        
        cancel_layout = QHBoxLayout()
        cancel_layout.addStretch()
        cancel_layout.addWidget(cancel_btn)
        cancel_layout.addStretch()
        layout.addLayout(cancel_layout)
        
        self._preview_modal.setLayout(layout)
        self._preview_modal.show()
    
    def _on_preview_generation_progress(self, current, total, image_name):
        if current < 0:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._on_preview_generation_complete)
            return
        
        QMetaObject.invokeMethod(self._preview_label, "setText",
                               Qt.ConnectionType.AutoConnection,
                               Q_ARG(str, f"Generating {current} of {total} previews..."))
        QMetaObject.invokeMethod(self._preview_progress, "setValue",
                               Qt.ConnectionType.AutoConnection,
                               Q_ARG(int, current))
        if image_name:
            QMetaObject.invokeMethod(self._preview_current_image_label, "setText",
                                   Qt.ConnectionType.AutoConnection,
                                   Q_ARG(str, f"Processing: {image_name}"))
    
    def _on_preview_generation_complete(self):
        if self._preview_label:
            self._preview_label.setText("All previews generated!")
        if self._preview_progress:
            self._preview_progress.setValue(self._preview_progress.maximum())
        if self._preview_current_image_label:
            self._preview_current_image_label.setText("")
        self._hide_preview_modal()
        self._load_preview_images()
        self._update_nav_dots()
        self._update_header()
        self._status_label.setText("Previews ready")
        self._status_label.setStyleSheet("color: #2ECC71; font-size: 12px;")
    
    def _on_preview_generation_cancel(self):
        self.aligner.cancel_preview_generation()
        self._hide_preview_modal()
        self._load_preview_images()
        self._status_label.setText("Preview generation cancelled")
        self._status_label.setStyleSheet("color: #E67E22; font-size: 12px;")
    
    def _hide_preview_modal(self):
        if self._preview_modal:
            modal = self._preview_modal
            self._preview_modal = None
            self._preview_label = None
            self._preview_progress = None
            self._preview_current_image_label = None
            modal.close()
            modal.deleteLater()
    
    def _on_tab_changed(self, index):
        """Handle tab change."""
        old_tab = self._current_tab
        self._current_tab = index
        logger.info(f"[TAB_CHANGE] {old_tab} -> {index}: current_idx={self.aligner.current_idx}, total_images={self.aligner.total_images}")
        
        if index == 0:
            self._is_preview_mode = False
            self._show_original_mode()
            self._load_current_images()
        else:
            self._is_preview_mode = True
            self._show_preview_mode()
            
            # Verify preview integrity before loading/generating
            logger.info(f"[TAB_CHANGE] Verifying preview integrity before generating...")
            self.aligner.verify_and_fix_preview_integrity()
            
            self._update_nav_dots()
            self._update_header()
            
            total, need_count = self.aligner.get_preview_generation_status()
            logger.info(f"[TAB_CHANGE] Preview status: total={total}, need_count={need_count}")
            
            if need_count > 0:
                logger.info(f"[TAB_CHANGE] Generating previews, need_count={need_count}")
                self._show_preview_modal(total)
                self.aligner.prepare_all_previews_async(
                    progress_callback=self._on_preview_generation_progress
                )
            else:
                logger.info(f"[TAB_CHANGE] Loading preview directly")
                self._load_preview_images()
    
    def _on_dot_clicked(self, idx):
        """Handle dot click navigation."""
        self.aligner.navigate_to(idx)
        self._pending_focal = None
        self._sync_all()
    
    def _on_page_clicked(self, idx):
        """Handle page dot click."""
        self.aligner.navigate_to(idx)
        self._pending_focal = None
        self._sync_all()

    def _on_dots_moved(self, from_index, to_index):
        """Handle drag-and-drop reordering of navigation dots."""
        if self.aligner.move_image(from_index, to_index):
            self._sync_all()
    
    def _on_save_and_next(self):
        """Save focal and move to next image."""
        if self._pending_focal:
            self.aligner.set_focal_point(self._pending_focal[0], self._pending_focal[1])
            self._pending_focal = None
        
        was_completed = self.aligner.is_current_completed()
        self.aligner.confirm_and_save()
        
        self._sync_all()
    
    def _on_skip(self):
        """Skip to next image."""
        if self.aligner.navigate(1):
            self._pending_focal = None
            self._sync_all()
    
    def _on_prev(self):
        """Navigate to previous image - no wrapping in original mode."""
        if self._current_tab == 0:  # Original mode - no wrapping
            if self.aligner.current_idx > 0:
                self.aligner.navigate(-1)
                self._pending_focal = None
                self._sync_all()
        else:  # Preview mode - with wrapping
            self.aligner.navigate_wrap(-1)
            self._sync_preview()
    
    def _on_next(self):
        """Navigate to next image - no wrapping in original mode."""
        logger.info(f"[NAV_NEXT] START: current_idx={self.aligner.current_idx}, tab={self._current_tab}")
        if self._current_tab == 0:  # Original mode - no wrapping
            if self.aligner.current_idx < self.aligner.total_images - 1:
                self.aligner.navigate(1)
                self._pending_focal = None
                logger.info(f"[NAV_NEXT] After navigate: current_idx={self.aligner.current_idx}")
                self._sync_all()
        else:  # Preview mode - with wrapping
            self.aligner.navigate_wrap(1)
            logger.info(f"[NAV_NEXT] After navigate_wrap: current_idx={self.aligner.current_idx}")
            self._sync_preview()
    
    def _on_toggle_preview(self):
        """Toggle preview mode."""
        if self._is_preview_mode:
            self._tabs.setCurrentIndex(0)
        else:
            self._tabs.setCurrentIndex(1)
            self._preview_orientation = "landscape"
            self.aligner.ensure_preview_for_current(self._preview_orientation)
    
    def _on_toggle_orientation(self):
        """Toggle between landscape and portrait preview in Preview mode."""
        if self._current_tab != 1:
            return
        
        self._preview_orientation = "portrait" if self._preview_orientation == "landscape" else "landscape"
        self.aligner.ensure_preview_for_current(self._preview_orientation)
        self._load_preview_images()
    
    def _on_clear_focal(self):
        """Clear focal point for current image."""
        self.aligner.clear_focal_point()
        self._main_image.clear_focal_point()
        self._pending_focal = None
        self._update_nav_dots()
        self._update_header()
    
    def _on_discard(self):
        """Discard current image - with unified sync."""
        logger.info(f"[DISCARD] START: current_idx={self.aligner.current_idx}, total_images={self.aligner.total_images}, tab={self._current_tab}, is_preview={self._is_preview_mode}")
        
        # Check if list becomes empty first
        if self.aligner.total_images <= 1:
            logger.warning(f"[DISCARD] Cannot discard last image!")
            QMessageBox.warning(
                self,
                "Cannot Discard",
                "Cannot discard the last image. At least one image must remain."
            )
            return
        
        logger.info(f"[DISCARD] Calling aligner.discard_current()...")
        self.aligner.discard_current()
        
        logger.info(f"[DISCARD] After discard: current_idx={self.aligner.current_idx}, total_images={self.aligner.total_images}")
        
        self._pending_focal = None
        
        # Use appropriate sync based on current mode
        if self._current_tab == 0:
            logger.info(f"[DISCARD] Using _sync_all() for original mode...")
            self._sync_all()
        else:
            logger.info(f"[DISCARD] Using _sync_preview() for preview mode...")
            self._sync_preview()
    
    def _on_reset_all(self):
        """Show confirmation modal for reset."""
        confirm_modal = QDialog(self)
        confirm_modal.setWindowTitle("Confirm Reset")
        confirm_modal.setModal(True)
        confirm_modal.setFixedSize(350, 150)
        confirm_modal.setStyleSheet("""
            QDialog {
                background-color: #1E1E2E;
            }
            QLabel {
                color: #E0E0E0;
                background-color: transparent;
            }
        """)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        message = QLabel("<b>Reset All Focal Points?</b>")
        message.setStyleSheet("color: #FFFFFF; font-size: 14px;")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        
        sub_message = QLabel("This will clear all focal points for all images.")
        sub_message.setStyleSheet("color: #A0A0B0; font-size: 12px;")
        sub_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub_message)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #3D3D5C;
                color: #FFFFFF;
                border: 1px solid #4D4D64;
                padding: 8px 20px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4D4D6C;
            }
        """)
        cancel_btn.clicked.connect(confirm_modal.close)
        
        reset_btn = QPushButton("Reset")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #8B3D3D;
                color: #FFFFFF;
                border: 1px solid #A04D4D;
                padding: 8px 20px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #9B4D4D;
            }
        """)
        
        def do_reset():
            confirm_modal.close()
            self.aligner.reset_all()
            self._pending_focal = None
            self._sync_all()
        
        reset_btn.clicked.connect(do_reset)
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(reset_btn)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        
        confirm_modal.setLayout(layout)
        confirm_modal.show()
    
    def _on_page_jump(self, count):
        """Jump by specified count."""
        self.aligner.page_jump(count)
        self._pending_focal = None
        self._sync_all()
    
    def _on_shift(self, direction):
        """Shift current image position."""
        if self.aligner.shift_current(direction):
            self._sync_all()
    
    def _show_position(self):
        """Show current position."""
        idx = self.aligner.current_idx
        total = self.aligner.total_images
        print(f"Current position: {idx + 1} / {total}")
    
    def _on_finish(self):
        """Show end menu dialog."""
        self._end_menu = EndMenu(self.aligner, self)
        self._end_menu.go_back_clicked.connect(self._on_end_menu_back)
        self._end_menu.export_complete.connect(self._on_export_complete)
        self._end_menu.show()
    
    def _on_end_menu_back(self):
        """Handle return from end menu."""
        pass  # Just close the dialog, nothing else needed
    
    def _on_export_complete(self, stats):
        """Handle export completion from end menu."""
        pass
    
    def _on_help(self):
        """Show help modal."""
        help_modal = QDialog(self)
        help_modal.setWindowTitle("Help")
        help_modal.setModal(True)
        help_modal.setFixedSize(400, 500)
        help_modal.setStyleSheet("""
            QDialog {
                background-color: #1E1E2E;
            }
            QLabel {
                color: #E0E0E0;
                background-color: transparent;
            }
        """)
        
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        title = QLabel("<b>Button Reference</b>")
        title.setStyleSheet("color: #FFFFFF; font-size: 16px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        buttons = [
            ("💾 Save", "Save focal point and move to next image", "Enter"),
            ("⏭ Skip", "Skip to next image without saving", "Space"),
            ("◀ / ▶", "Navigate between images", "← / →"),
            ("👁 Preview", "Toggle preview mode", "P"),
            ("↻ Orientation", "Toggle landscape/portrait in preview", "O"),
            ("⌫ Clear", "Clear focal point from current image", "Delete"),
            ("🗑 Remove", "Remove current image from the set", "X"),
            ("🔄 Reset", "Reset all focal points", "R"),
            ("✨ Finish", "Export aligned images", "F"),
            ("🚪 Quit", "Quit the aligner", "Escape"),
        ]
        
        for icon, desc, shortcut in buttons:
            row = QHBoxLayout()
            row.setSpacing(10)
            
            icon_label = QLabel(icon)
            icon_label.setStyleSheet("font-size: 18px; width: 30px; text-align: center;")
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            desc_label = QLabel(desc)
            desc_label.setStyleSheet("font-size: 13px;")
            
            shortcut_label = QLabel(f"({shortcut})")
            shortcut_label.setStyleSheet("color: #60E080; font-size: 12px; font-weight: bold;")
            shortcut_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            
            row.addWidget(icon_label, 0)
            row.addWidget(desc_label, 1)
            row.addWidget(shortcut_label, 0)
            
            layout.addLayout(row)
        
        layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3D3D5C;
                color: #FFFFFF;
                border: 1px solid #4D4D64;
                padding: 8px 24px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4D4D6C;
            }
        """)
        close_btn.clicked.connect(help_modal.close)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        
        help_modal.setLayout(layout)
        help_modal.show()
    
    def _on_quit(self):
        """Quit the aligner."""
        # Close preview modal if open
        self._hide_preview_modal()
        
        stats = self.aligner.get_stats()
        self.aligner_finished.emit(stats)
    
    def closeEvent(self, event):
        """Handle window close."""
        event.accept()