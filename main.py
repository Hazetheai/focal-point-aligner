#!/usr/bin/env python3
"""
Main entry point for the Focal Point Aligner GUI application.
"""

import os
import platform
import sys

# Set Qt platform plugin before Qt is imported
if 'QT_QPA_PLATFORM' not in os.environ:
    system = platform.system()
    if system == 'Darwin':
        os.environ['QT_QPA_PLATFORM'] = 'cocoa'
    elif system == 'Windows':
        os.environ['QT_QPA_PLATFORM'] = 'windows'
    else:
        os.environ['QT_QPA_PLATFORM'] = 'xcb'

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt

import styles
from aligner_core import DEFAULT_MAX_ZOOM
from ui.opener_screen import OpenerScreen
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
        
        self.batch_mode = False
        self.batch_root = None
        self.batch_manager = None
        self._batch_target_width = 2560
        self._batch_target_height = 1440
        self._batch_max_zoom = DEFAULT_MAX_ZOOM
        self._batch_seen = set()
    
    def start(self):
        """Start the application with the opener screen."""
        self.opener = OpenerScreen()
        self.opener.start_clicked.connect(self.on_start_clicked)
        self.opener.batch_started.connect(self.on_batch_started)
        self.opener.show()
    
    def start_with_config(self, config):
        """Start directly with aligner screen using provided config."""
        self.current_config = config
        self.aligner_screen = AlignerScreen(config)
        self.aligner_screen.aligner_finished.connect(self.on_aligner_finished)
        self.aligner_screen.quit_requested.connect(self.on_aligner_finished)
        self.aligner_screen.show()
    
    def on_start_clicked(self, config: dict):
        """Handle start button click from opener (single-folder mode)."""
        self.current_config = config
        self.batch_mode = False
        self.batch_root = None
        self.batch_manager = None
        
        self.opener.hide()
        
        self.aligner_screen = AlignerScreen(config)
        self.aligner_screen.aligner_finished.connect(self.on_aligner_finished)
        self.aligner_screen.quit_requested.connect(self.on_aligner_finished)
        self.aligner_screen.show()

    def on_batch_started(self, config: dict):
        """Enter batch mode: hide opener and load the first pending sub-folder."""
        from pathlib import Path
        from batch import BatchManager
        self.batch_mode = True
        self.batch_root = Path(config['root'])
        self.batch_manager = BatchManager(self.batch_root)
        self._batch_target_width = config.get('target_width', 2560)
        self._batch_target_height = config.get('target_height', 1440)
        self._batch_max_zoom = config.get('max_zoom', DEFAULT_MAX_ZOOM)
        self._batch_seen = set()
        self.opener.hide()
        self._open_next_batch_folder()

    def _open_next_batch_folder(self):
        """Load the next pending batch folder into the aligner, or show the
        all-complete queue in the opener. Folders already opened this session
        (e.g. escaped without exporting) are skipped so auto-advance never
        loops back onto the same batch."""
        nxt = None
        for folder in self.batch_manager.discover_subfolders():
            if folder in self._batch_seen:
                continue
            if not self.batch_manager.is_done(folder):
                nxt = folder
                break
        if nxt is None:
            self.opener.refresh_batch_queue()
            self.opener.show()
            self.opener.raise_()
            self.opener.activateWindow()
            return
        self._batch_seen.add(nxt)
        config = {
            'input_folder': str(nxt),
            'output_folder': str(self.batch_manager.aligned_output_for(nxt)),
            'target_width': self._batch_target_width,
            'target_height': self._batch_target_height,
            'max_zoom': self._batch_max_zoom,
        }
        self.current_config = config
        self.aligner_screen = AlignerScreen(config)
        self.aligner_screen.aligner_finished.connect(self.on_aligner_finished)
        self.aligner_screen.quit_requested.connect(self.on_aligner_finished)
        self.aligner_screen.show()

    def on_aligner_finished(self, stats: dict):
        """Handle aligner completion. Single mode: return to the opener screen.
        Batch mode: tear down and auto-open the next pending sub-folder."""
        if self.aligner_screen:
            self.aligner_screen.close()
            self.aligner_screen.deleteLater()
            self.aligner_screen = None
        if self.batch_mode and self.batch_manager:
            self._open_next_batch_folder()
        else:
            self._show_opener()
    
    def _show_opener(self):
        """Show (or recreate) the opener screen."""
        if self.opener:
            self.opener.show()
            self.opener.raise_()
            self.opener.activateWindow()
        else:
            self.start()
    
    def on_new_batch(self):
        """Handle new batch button."""
        if self.opener:
            self.opener.hide()
        
        self.opener = OpenerScreen()
        self.opener.start_clicked.connect(self.on_start_clicked)
        self.opener.show()


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Focal Point Aligner GUI")
    parser.add_argument('--config', type=str, help='Path to config.json to skip opener screen')
    args = parser.parse_args()
    
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
    
    if args.config:
        import json
        from pathlib import Path
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"Error: Config file not found: {args.config}", file=sys.stderr)
            sys.exit(1)
        with open(config_path, 'r') as f:
            config = json.load(f)
        app.start_with_config(config)
    else:
        app.start()
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())