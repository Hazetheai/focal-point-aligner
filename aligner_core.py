#!/usr/bin/env python3
"""
Core logic for Focal Point Aligner - extracted from align_focal_points.py
Contains all image processing, focal point management, and navigation logic.
No UI code - designed to be used by PyQt6 UI.
"""

import json
import shutil
from pathlib import Path

import cv2
import numpy as np


def calculate_transformation(focal_x, focal_y, orig_w, orig_h, target_w, target_h):
    """
    Calculate transformation to center focal point and fill target frame.
    """
    focal_x = max(1, min(focal_x, orig_w - 1))
    focal_y = max(1, min(focal_y, orig_h - 1))
    
    half_target_w = target_w / 2
    half_target_h = target_h / 2
    
    scale_fill = max(orig_w / target_w, orig_h / target_h)
    
    scale_horizontal = max(
        half_target_w / focal_x if focal_x > 0 else float('inf'),
        half_target_w / (orig_w - focal_x) if (orig_w - focal_x) > 0 else float('inf')
    )
    
    scale_vertical = max(
        half_target_h / focal_y if focal_y > 0 else float('inf'),
        half_target_h / (orig_h - focal_y) if (orig_h - focal_y) > 0 else float('inf')
    )
    
    scale_focal = max(scale_horizontal, scale_vertical)
    
    scale = max(scale_fill, scale_focal)
    
    if scale == float('inf') or scale > 100:
        scale = scale_fill
    
    scaled_w = orig_w * scale
    scaled_h = orig_h * scale
    
    focal_scaled_x = focal_x * scale
    focal_scaled_y = focal_y * scale
    
    tx = half_target_w - focal_scaled_x
    ty = half_target_h - focal_scaled_y
    
    crop_x = -tx
    crop_y = -ty
    
    return crop_x, crop_y, scale, target_w, target_h


class FocalPointAlignerCore:
    """
    Core Focal Point Aligner - all processing logic without UI.
    """
    
    def __init__(self, config: dict = None):
        """
        Initialize the Focal Point Aligner Core.
        
        Args:
            config: Dictionary containing:
                - input_folder: Path to input images
                - output_folder: Path for output (optional, defaults to input_aligned)
                - target_width: Target width for aligned images (optional, default 2560)
                - target_height: Target height for aligned images (optional, default 1440)
        """
        if config is None:
            config = {}
        
        self.input_folder = Path(config.get('input_folder', '.'))
        
        default_output = self.input_folder.parent / f"{self.input_folder.name}_aligned"
        self.output_folder = Path(config.get('output_folder', default_output))
        self.output_folder.mkdir(parents=True, exist_ok=True)
        
        self.target_width = config.get('target_width', 2560)
        self.target_height = config.get('target_height', 1440)
        
        self.preview_landscape_folder = self.output_folder.parent / f"{self.output_folder.name}_preview_landscape"
        self.preview_portrait_folder = self.output_folder.parent / f"{self.output_folder.name}_preview_portrait"
        
        self.json_path = self.output_folder / "focal_points.json"
        
        self.alignment_mode = None
        self.preview_state = {}
        self.discarded = set()
        
        if self.json_path.exists():
            try:
                with open(self.json_path, 'r') as f:
                    data = json.load(f)
                if "alignment_mode" in data and data["alignment_mode"]:
                    self.alignment_mode = data["alignment_mode"]
                if "preview_state" in data:
                    self.preview_state = data["preview_state"]
                if "discarded" in data:
                    self.discarded = set(data["discarded"])
            except:
                pass
        
        extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
        self.image_files = sorted([
            f for f in self.input_folder.iterdir()
            if f.is_file() and f.suffix.lower() in extensions
        ])
        
        if not self.image_files:
            raise ValueError(f"No images found in {self.input_folder}")
        
        self.current_idx = 0
        self.focal_points = {}
        self.completed = set()
        self.image_dimensions = {}
        
        self.load_focal_points()
        
        if self.image_files:
            sample_img = cv2.imread(str(self.image_files[0]))
            if sample_img is not None:
                self.ref_h, self.ref_w = sample_img.shape[:2]
            else:
                self.ref_h, self.ref_w = 1440, 2560
        else:
            self.ref_h, self.ref_w = 1440, 2560
    
    @property
    def preview_folder(self):
        if self.alignment_mode == "landscape":
            return self.preview_landscape_folder
        elif self.alignment_mode == "portrait":
            return self.preview_portrait_folder
        return None
    
    @property
    def total_images(self):
        return len(self.image_files)
    
    @property
    def completed_count(self):
        return len(self.completed)
    
    def load_focal_points(self):
        if self.json_path.exists():
            try:
                with open(self.json_path, 'r') as f:
                    data = json.load(f)
                
                if "alignment_mode" in data:
                    self.alignment_mode = data["alignment_mode"]
                
                if "preview_state" in data:
                    self.preview_state = data["preview_state"]
                
                if "discarded" in data:
                    self.discarded = set(data["discarded"])
                
                focal_data = {k: v for k, v in data.items() 
                              if k not in ["alignment_mode", "preview_state", "discarded"]}
                
                existing_files = {f.name for f in self.image_files}
                
                for filename, coords in focal_data.items():
                    if filename not in existing_files:
                        continue
                    for idx, img_file in enumerate(self.image_files):
                        if img_file.name == filename:
                            if len(coords) >= 4:
                                self.focal_points[idx] = (coords[0], coords[1])
                                self.image_dimensions[idx] = (coords[2], coords[3])
                            else:
                                self.focal_points[idx] = tuple(coords)
                            self.completed.add(idx)
                            break
                
                if self.focal_points:
                    first_pending = 0
                    for i in range(len(self.image_files)):
                        if i not in self.completed:
                            first_pending = i
                            break
                    else:
                        first_pending = len(self.image_files) - 1
                    
                    self.current_idx = first_pending
            except Exception as e:
                print(f"Warning: Could not load focal points: {e}")
    
    def save_focal_points(self):
        stale_indices = [idx for idx in self.focal_points.keys() if idx >= len(self.image_files)]
        for idx in stale_indices:
            del self.focal_points[idx]
            self.completed.discard(idx)
        
        data = {}
        for idx, focal in self.focal_points.items():
            if idx < len(self.image_files):
                filename = self.image_files[idx].name
                dims = self.image_dimensions.get(idx)
                if dims:
                    data[filename] = [focal[0], focal[1], dims[0], dims[1]]
                else:
                    data[filename] = list(focal)
        
        if self.alignment_mode:
            data["alignment_mode"] = self.alignment_mode
        
        if self.preview_state:
            data["preview_state"] = self.preview_state
        
        if self.discarded:
            data["discarded"] = list(self.discarded)
        
        try:
            with open(self.json_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save focal points: {e}")
    
    def get_current_image(self):
        """Load and return the current original image."""
        if 0 <= self.current_idx < len(self.image_files):
            img = cv2.imread(str(self.image_files[self.current_idx]))
            if img is not None:
                h, w = img.shape[:2]
                self.image_dimensions[self.current_idx] = (w, h)
            return img
        return None
    
    def get_current_focal(self):
        """Get focal point for current image."""
        return self.focal_points.get(self.current_idx)
    
    def get_prev_image(self, count=1):
        """Load previous image(s) for thumbnail."""
        prev_idx = self.current_idx - count
        if prev_idx >= 0:
            img = cv2.imread(str(self.image_files[prev_idx]))
            if img is not None:
                return img, self.focal_points.get(prev_idx)
        return None, None
    
    def get_next_image(self, count=1):
        """Load next image(s) for thumbnail."""
        next_idx = self.current_idx + count
        if next_idx < len(self.image_files):
            img = cv2.imread(str(self.image_files[next_idx]))
            if img is not None:
                return img, self.focal_points.get(next_idx)
        return None, None
    
    def get_preview_image(self, orientation="landscape"):
        """Load preview image for current index."""
        folder = self.preview_landscape_folder if orientation == "landscape" else self.preview_portrait_folder
        if folder is None:
            return None
        filename = f"{self.current_idx + 1:04d}.jpg"
        preview_path = folder / filename
        if preview_path.exists():
            return cv2.imread(str(preview_path))
        return None
    
    def set_focal_point(self, x, y):
        """Set focal point for current image (in original image coordinates)."""
        h, w = self.image_dimensions.get(self.current_idx, (0, 0))
        if h == 0 or w == 0:
            img = cv2.imread(str(self.image_files[self.current_idx]))
            if img is not None:
                h, w = img.shape[:2]
                self.image_dimensions[self.current_idx] = (w, h)
        
        self.focal_points[self.current_idx] = (float(x), float(y))
        self.completed.add(self.current_idx)
    
    def clear_focal_point(self):
        """Clear focal point for current image."""
        if self.current_idx in self.focal_points:
            del self.focal_points[self.current_idx]
        if self.current_idx in self.completed:
            self.completed.remove(self.current_idx)
        self.save_focal_points()
    
    def confirm_and_save(self):
        """Save current focal point and generate aligned images."""
        if self.current_idx not in self.focal_points:
            img = self.get_current_image()
            if img is not None:
                h, w = img.shape[:2]
                self.focal_points[self.current_idx] = (w / 2, h / 2)
                self.image_dimensions[self.current_idx] = (w, h)
            else:
                return False
        
        if self.current_idx not in self.image_dimensions:
            img = self.get_current_image()
            if img is not None:
                h, w = img.shape[:2]
                self.image_dimensions[self.current_idx] = (w, h)
        
        if self.current_idx not in self.completed:
            self.completed.add(self.current_idx)
        
        self.save_aligned_image()
        
        focal = self.focal_points[self.current_idx]
        
        self.align_single_image(self.current_idx, self.image_files[self.current_idx], 
                               focal, self.preview_landscape_folder, "landscape")
        self.align_single_image(self.current_idx, self.image_files[self.current_idx], 
                               focal, self.preview_portrait_folder, "portrait")
        
        self.save_focal_points()
        
        if self.current_idx < len(self.image_files) - 1:
            self.current_idx += 1
        
        return True
    
    def save_aligned_image(self):
        """Save centered (non-cropped) image to output folder."""
        img = self.get_current_image()
        if img is None:
            return
        
        h, w = img.shape[:2]
        fx, fy = self.focal_points.get(self.current_idx, (w/2, h/2))
        
        center = np.array([w / 2, h / 2])
        focal = np.array([fx, fy])
        translation = center - focal
        
        M = np.float32([[1, 0, translation[0]], [0, 1, translation[1]]])
        aligned = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
        
        output_name = f"{self.current_idx + 1:04d}.jpg"
        output_path = self.output_folder / output_name
        cv2.imwrite(str(output_path), aligned, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
    def align_single_image(self, idx, img_file, focal, output_folder, orientation):
        """Align a single image with given focal point to specified orientation."""
        if focal is None:
            img = cv2.imread(str(img_file))
            if img is not None:
                h, w = img.shape[:2]
                focal = (w / 2, h / 2)
            else:
                return
        
        if orientation == "landscape":
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
        
        output_folder.mkdir(parents=True, exist_ok=True)
        output_name = f"{idx + 1:04d}.jpg"
        output_path = output_folder / output_name
        cv2.imwrite(str(output_path), aligned, [cv2.IMWRITE_JPEG_QUALITY, 90])
    
    def prepare_aligned_previews(self, orientation="landscape"):
        """Pre-generate all preview images for the given orientation."""
        folder = self.preview_landscape_folder if orientation == "landscape" else self.preview_portrait_folder
        folder.mkdir(parents=True, exist_ok=True)
        
        existing_count = len(list(folder.glob("*.jpg")))
        if existing_count == len(self.image_files):
            return
        
        for f in folder.glob("*.jpg"):
            f.unlink()
        
        for idx, img_file in enumerate(self.image_files):
            current_focal = self.focal_points.get(idx)
            if current_focal is None:
                img = cv2.imread(str(img_file))
                if img is not None:
                    h, w = img.shape[:2]
                    current_focal = (w / 2, h / 2)
                    self.focal_points[idx] = current_focal
            
            if current_focal is not None:
                self.align_single_image(idx, img_file, current_focal, folder, orientation)
        
        self.save_focal_points()
    
    def navigate(self, direction):
        """Navigate to previous/next image."""
        new_idx = self.current_idx + direction
        if 0 <= new_idx < len(self.image_files):
            self.current_idx = new_idx
            return True
        return False
    
    def navigate_to(self, idx):
        """Navigate to specific index."""
        if 0 <= idx < len(self.image_files):
            self.current_idx = idx
            return True
        return False
    
    def page_jump(self, count):
        """Jump by specified number of images."""
        new_idx = max(0, min(len(self.image_files) - 1, self.current_idx + count))
        self.current_idx = new_idx
    
    def shift_current(self, direction):
        """Reorder current image with neighbor."""
        if direction == -1:
            if self.current_idx > 0:
                self._swap_indices(self.current_idx, self.current_idx - 1)
                return True
        else:
            if self.current_idx < len(self.image_files) - 1:
                self._swap_indices(self.current_idx, self.current_idx + 1)
                return True
        return False
    
    def _swap_indices(self, i, j):
        """Swap images at indices i and j."""
        self.image_files[i], self.image_files[j] = self.image_files[j], self.image_files[i]
        
        new_focal = {}
        for idx, focal in self.focal_points.items():
            if idx == i:
                new_focal[j] = focal
            elif idx == j:
                new_focal[i] = focal
            else:
                new_focal[idx] = focal
        self.focal_points = new_focal
        
        new_completed = set()
        for idx in self.completed:
            if idx == i:
                new_completed.add(j)
            elif idx == j:
                new_completed.add(i)
            else:
                new_completed.add(idx)
        self.completed = new_completed
        
        self.save_focal_points()
    
    def discard_current(self):
        """Move current image to discarded folder."""
        current_file = self.image_files[self.current_idx]
        discard_folder = self.input_folder / "discarded"
        discard_folder.mkdir(exist_ok=True)
        
        dest = discard_folder / current_file.name
        shutil.move(str(current_file), str(dest))
        
        self.discarded.add(current_file.name)
        if self.current_idx in self.focal_points:
            del self.focal_points[self.current_idx]
            self.completed.discard(self.current_idx)
        
        self.save_focal_points()
        
        extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
        self.image_files = sorted([
            f for f in self.input_folder.iterdir()
            if f.is_file() and f.suffix.lower() in extensions
        ])
        
        if self.current_idx >= len(self.image_files):
            self.current_idx = max(0, len(self.image_files) - 1)
    
    def reset_all(self):
        """Reset all focal points and preview images."""
        for idx in list(self.focal_points.keys()):
            del self.focal_points[idx]
        self.completed.clear()
        
        if self.json_path.exists():
            self.json_path.unlink()
        
        for folder in [self.preview_landscape_folder, self.preview_portrait_folder]:
            if folder and folder.exists():
                shutil.rmtree(folder)
        
        self.current_idx = 0
        self.alignment_mode = None
        self.save_focal_points()
    
    def set_alignment_mode(self, mode):
        """Set the alignment mode (landscape/portrait/None for original)."""
        self.alignment_mode = mode
        self.save_focal_points()
    
    def get_stats(self):
        """Return statistics about the current session."""
        total = len(self.image_files)
        with_focal = len(self.focal_points)
        
        center_count = 0
        for idx, focal in self.focal_points.items():
            dims = self.image_dimensions.get(idx)
            if dims:
                center_x = dims[0] / 2
                center_y = dims[1] / 2
                if abs(focal[0] - center_x) <= 1 and abs(focal[1] - center_y) <= 1:
                    center_count += 1
        
        return {
            'total': total,
            'with_focal': with_focal,
            'center_focal': center_count,
            'without_focal': total - with_focal,
            'input_folder': str(self.input_folder),
            'output_folder': str(self.output_folder),
            'target_width': self.target_width,
            'target_height': self.target_height,
        }
    
    def is_complete(self):
        """Check if all images have focal points."""
        return len(self.completed) == len(self.image_files)
    
    def get_current_filename(self):
        """Get filename of current image."""
        if 0 <= self.current_idx < len(self.image_files):
            return self.image_files[self.current_idx].name
        return ""
    
    def is_current_completed(self):
        """Check if current image has a focal point."""
        return self.current_idx in self.completed
    
    def is_focal_at_center(self):
        """Check if current focal point is at image center."""
        focal = self.focal_points.get(self.current_idx)
        dims = self.image_dimensions.get(self.current_idx)
        if focal and dims:
            center_x = dims[0] / 2
            center_y = dims[1] / 2
            return abs(focal[0] - center_x) <= 1 and abs(focal[1] - center_y) <= 1
        return False