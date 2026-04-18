"""
Main window wrapper that hosts the OpenCV display area within PyQt.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal

import cv2
import numpy as np

import styles
from align_focal_points import FocalPointAligner, WINDOW_NAME, DISPLAY_HEIGHT, DISPLAY_WIDTH


class MainWindow(QWidget):
    """Main window that hosts the OpenCV Focal Point Aligner."""
    
    # Signal emitted when user exits the aligner
    aligner_finished = pyqtSignal(dict)
    
    def __init__(self, config: dict, parent=None):
        """
        Initialize the main window.
        
        Args:
            config: Dictionary containing:
                - input_folder: Path to input images
                - output_folder: Path for output
                - target_width: Target width
                - target_height: Target height
        """
        self.config = config
        self.aligner = None
        
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Focal Point Aligner")
        self.setMinimumSize(DISPLAY_WIDTH, DISPLAY_HEIGHT)
        
        # Apply palette
        self.setPalette(styles.get_palette())
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Placeholder label (OpenCV will create its own window)
        self.placeholder = QLabel("Click Start to begin aligning images...")
        self.placeholder.setStyleSheet("""
            QLabel {
                background-color: #1E1E2E;
                color: #A0A0B0;
                font-size: 24px;
            }
        """)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setMinimumSize(DISPLAY_WIDTH, DISPLAY_HEIGHT)
        
        layout.addWidget(self.placeholder)
        
        self.setLayout(layout)
    
    def start_aligner(self):
        """Start the focal point aligner (runs in main thread, blocks Qt)."""
        try:
            # Hide this window - aligner creates its own window
            self.hide()
            
            # Import and run aligner here to handle any errors better
            from align_focal_points import FocalPointAligner
            
            self.aligner = FocalPointAligner(self.config)
            
            # Run the aligner (blocks until done)
            result = self.aligner.run()
            
            # Get stats
            stats = self.aligner.get_stats()
            stats['input_folder'] = str(self.aligner.input_folder)
            stats['output_folder'] = str(self.aligner.output_folder)
            stats['target_width'] = self.aligner.target_width
            stats['target_height'] = self.aligner.target_height
            
            # Show Qt window again
            self.show()
            
            # Emit finished signal with stats
            self.aligner_finished.emit(stats)
            
        except Exception as e:
            import traceback
            print(f"Error in aligner: {e}")
            traceback.print_exc()
            self.show()
            self.aligner_finished.emit({'error': str(e), 'total': 0})
    
    def closeEvent(self, event):
        """Handle window close event."""
        event.accept()