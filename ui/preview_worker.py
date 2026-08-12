"""
Background worker for generating preview images.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtCore import QThread, pyqtSignal

import cv2
import numpy as np

from aligner_core import render_aligned


class PreviewWorker(QThread):
    """
    Background thread for generating preview images.
    """
    
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, aligner_core, orientation="landscape", parent=None):
        super().__init__(parent)
        self.aligner = aligner_core
        self.orientation = orientation
    
    def run(self):
        try:
            if self.orientation == "landscape":
                folder = self.aligner.preview_landscape_folder
            else:
                folder = self.aligner.preview_portrait_folder
            
            folder.mkdir(parents=True, exist_ok=True)
            
            total = len(self.aligner.image_files)
            
            for idx, img_file in enumerate(self.aligner.image_files):
                self.progress.emit(idx + 1, total)
                
                current_focal = self.aligner.focal_points.get(idx)
                if current_focal is None:
                    img = cv2.imread(str(img_file))
                    if img is not None:
                        h, w = img.shape[:2]
                        current_focal = (w / 2, h / 2)
                        self.aligner.focal_points[idx] = current_focal
                
                if current_focal is not None:
                    self._align_single_image(idx, img_file, current_focal, folder)
            
            self.aligner.save_focal_points()
            self.finished.emit(self.orientation)
            
        except Exception as e:
            self.error.emit(str(e))
    
    def _align_single_image(self, idx, img_file, focal, output_folder):
        """Align a single preview image to the configured target dims."""
        if self.orientation == "landscape":
            target_w = self.aligner.target_width
            target_h = self.aligner.target_height
        else:
            target_w = self.aligner.target_height
            target_h = self.aligner.target_width

        img = cv2.imread(str(img_file))
        if img is None:
            return

        aligned, _ = render_aligned(
            img, focal, target_w, target_h, max_zoom=self.aligner.max_zoom
        )

        output_name = f"{idx:04d}.jpg"
        output_path = output_folder / output_name
        cv2.imwrite(str(output_path), aligned, [cv2.IMWRITE_JPEG_QUALITY, 90])