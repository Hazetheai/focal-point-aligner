"""
Background worker for generating preview images.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtCore import QThread, pyqtSignal

import cv2
import numpy as np

from aligner_core import calculate_transformation


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
        """Align a single image."""
        if self.orientation == "landscape":
            target_w, target_h = 2560, 1440
        else:
            target_w, target_h = 1440, 2560
        
        img = cv2.imread(str(img_file))
        if img is None:
            return
        
        h, w = img.shape[:2]
        focal_x, focal_y = focal
        
        if abs(focal_x - w / 2) <= 1 and abs(focal_y - h / 2) <= 1:
            aligned = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
        else:
            crop_x, crop_y, scale, crop_w, crop_h = calculate_transformation(
                focal_x, focal_y, w, h, target_w, target_h
            )
            
            scaled_w = int(w * scale)
            scaled_h = int(h * scale)
            scaled = cv2.resize(img, (scaled_w, scaled_h), interpolation=cv2.INTER_LANCZOS4)
            
            src_x = max(0, int(crop_x))
            src_y = max(0, int(crop_y))
            src_w = min(crop_w, scaled_w - src_x)
            src_h = min(crop_h, scaled_h - src_y)
            
            aligned = scaled[src_y:src_y + src_h, src_x:src_x + src_w]
            
            if aligned.shape[0] != crop_h or aligned.shape[1] != crop_w:
                aligned = cv2.resize(aligned, (crop_w, crop_h), interpolation=cv2.INTER_LANCZOS4)
        
        output_name = f"{idx:04d}.jpg"
        output_path = output_folder / output_name
        cv2.imwrite(str(output_path), aligned, [cv2.IMWRITE_JPEG_QUALITY, 90])