#!/usr/bin/env python3
"""
Main entry point for the Focal Point Aligner GUI application.
"""

import sys

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt

import styles
from ui.opener_screen import OpenerScreen
from ui.closer_screen import CloserScreen
from ui.aligner_screen import AlignerScreen
from ui.logger import logger


class FocalPointAlignerApp(QApplication):
    """Main application class for the Focal Point Aligner."""
    
    def __init__(self):
        super().__init__(sys.argv)
        
        self.setApplicationName("Focal Point Aligner")
        self.setApplicationVersion("1.0.0")
        
        self.setPalette(styles.get_palette())
        
        self.opener = None
        self.aligner_screen = None
        self.closer = None
        self.current_config = None
    
    def start(self):
        """Start the application with the opener screen."""
        self.opener = OpenerScreen()
        self.opener.start_clicked.connect(self.on_start_clicked)
        self.opener.show()
    
    def on_start_clicked(self, config: dict):
        """Handle start button click from opener."""
        self.current_config = config
        
        self.opener.hide()
        
        self.aligner_screen = AlignerScreen(config)
        self.aligner_screen.aligner_finished.connect(self.on_aligner_finished)
        self.aligner_screen.quit_requested.connect(self.on_aligner_finished)
        self.aligner_screen.show()
    
    def on_aligner_finished(self, stats: dict):
        """Handle aligner completion."""
        if self.aligner_screen:
            self.aligner_screen.hide()
            self.aligner_screen = None
        
        self.closer = CloserScreen(stats)
        self.closer.new_batch_clicked.connect(self.on_new_batch)
        self.closer.exit_clicked.connect(self.quit)
        self.closer.show()
    
    def on_new_batch(self):
        """Handle new batch button from closer."""
        if self.closer:
            self.closer.hide()
            self.closer = None
        
        if not self.opener:
            self.opener = OpenerScreen()
            self.opener.start_clicked.connect(self.on_start_clicked)
        self.opener.show()


def main():
    """Main entry point."""
    logger.info("=== Focal Point Aligner starting ===")
    app = FocalPointAlignerApp()
    
    def exception_hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Error")
        msg.setText(f"An unexpected error occurred:\n{exc_type.__name__}: {exc_value}")
        msg.exec()
    
    sys.excepthook = exception_hook
    
    app.start()
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())