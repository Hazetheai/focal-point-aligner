#!/usr/bin/env python3
"""
Core logic for Focal Point Aligner - extracted from align_focal_points.py
Contains all image processing, focal point management, and navigation logic.
No UI code - designed to be used by PyQt6 UI.
"""

import json
import shutil
import threading
import time
from pathlib import Path
from datetime import datetime

import cv2

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
import numpy as np

JSON_VERSION = "2.0"


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
    
    if scale == float('inf') or scale > 50:
        scale = scale_fill
    
    # Additional safety: cap scale to prevent memory issues with huge images
    if scale > 20:
        scale = 20
    
    scaled_w = orig_w * scale
    scaled_h = orig_h * scale
    
    focal_scaled_x = focal_x * scale
    focal_scaled_y = focal_y * scale
    
    tx = half_target_w - focal_scaled_x
    ty = half_target_h - focal_scaled_y
    
    crop_x = -tx
    crop_y = -ty
    
    return crop_x, crop_y, scale, target_w, target_h


def load_image_safely(img_path):
    """Load an image using OpenCV, with PIL fallback for problematic formats."""
    # Try OpenCV first
    img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
    if img is not None and img.size > 0:
        return img, "opencv"
    
    # Fallback to PIL/Pillow for formats like WEBP that might cause issues
    if not PIL_AVAILABLE:
        return None, "failed"
    
    try:
        pil_img = Image.open(str(img_path))
        if pil_img.mode != 'RGB':
            pil_img = pil_img.convert('RGB')
        img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        return img, "pil"
    except Exception:
        return None, "failed"


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
        self.auto_center_flags = {}
        
        self.preview_dirty = set()
        self._cancel_preview_generation = False
        self._preview_generation_lock = threading.Lock()
        
        self.load_focal_points()
        
        if self.image_files:
            for idx in range(len(self.image_files)):
                landscape_file = self.preview_landscape_folder / f"{idx + 1:04d}.jpg"
                portrait_file = self.preview_portrait_folder / f"{idx + 1:04d}.jpg"
                if not landscape_file.exists() or not portrait_file.exists():
                    self.preview_dirty.add(idx)
        
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
                              if k not in ["alignment_mode", "preview_state", "discarded", "_meta"]}
                
                existing_files = {f.name for f in self.image_files}
                
                for filename, coords in focal_data.items():
                    if filename not in existing_files:
                        continue
                    for idx, img_file in enumerate(self.image_files):
                        if img_file.name == filename:
                            if isinstance(coords, dict):
                                self.focal_points[idx] = (coords.get("focal_x", 0), coords.get("focal_y", 0))
                                self.image_dimensions[idx] = (coords.get("original_width", 0), coords.get("original_height", 0))
                                self.auto_center_flags[idx] = coords.get("auto_center", False)
                            elif isinstance(coords, list) and len(coords) >= 4:
                                self.focal_points[idx] = (coords[0], coords[1])
                                self.image_dimensions[idx] = (coords[2], coords[3])
                                self.auto_center_flags[idx] = False
                            elif isinstance(coords, list) and len(coords) >= 2:
                                self.focal_points[idx] = (coords[0], coords[1])
                                self.auto_center_flags[idx] = False
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
            if idx in self.auto_center_flags:
                del self.auto_center_flags[idx]
        
        data = {"_meta": {
            "version": JSON_VERSION,
            "target_width": self.target_width,
            "target_height": self.target_height
        }}
        
        for idx, focal in self.focal_points.items():
            if idx < len(self.image_files):
                filename = self.image_files[idx].name
                dims = self.image_dimensions.get(idx, (0, 0))
                auto_center = self.auto_center_flags.get(idx, False)
                data[filename] = {
                    "focal_x": focal[0],
                    "focal_y": focal[1],
                    "original_width": dims[0],
                    "original_height": dims[1],
                    "auto_center": auto_center,
                    "timestamp": datetime.now().isoformat()
                }
        
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
    
    def delete_focal_points_file(self):
        """Delete the focal points JSON file."""
        if self.json_path.exists():
            try:
                self.json_path.unlink()
            except Exception as e:
                print(f"Warning: Could not delete focal points file: {e}")
    
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
    
    def set_focal_point(self, x, y, auto_center=False):
        """Set focal point for current image (in original image coordinates)."""
        h, w = self.image_dimensions.get(self.current_idx, (0, 0))
        if h == 0 or w == 0:
            img = cv2.imread(str(self.image_files[self.current_idx]))
            if img is not None:
                h, w = img.shape[:2]
                self.image_dimensions[self.current_idx] = (w, h)
        
        self.focal_points[self.current_idx] = (float(x), float(y))
        self.auto_center_flags[self.current_idx] = auto_center
        self.completed.add(self.current_idx)
        
        with self._preview_generation_lock:
            self.preview_dirty.add(self.current_idx)
        
        focal = (float(x), float(y))
        thread = threading.Thread(
            target=self._generate_previews_for_image,
            args=(self.current_idx, focal)
        )
        thread.daemon = True
        thread.start()
    
    def clear_focal_point(self):
        """Clear focal point for current image."""
        if self.current_idx in self.focal_points:
            del self.focal_points[self.current_idx]
        if self.current_idx in self.auto_center_flags:
            del self.auto_center_flags[self.current_idx]
        if self.current_idx in self.completed:
            self.completed.remove(self.current_idx)
        self.save_focal_points()
    
    def _generate_previews_for_image(self, idx, focal):
        """Background preview generation for a single image."""
        self.align_single_image(idx, self.image_files[idx], focal,
                               self.preview_landscape_folder, "landscape")
        self.align_single_image(idx, self.image_files[idx], focal,
                               self.preview_portrait_folder, "portrait")
        with self._preview_generation_lock:
            self.preview_dirty.discard(idx)
        self.save_focal_points()
    
    def get_preview_generation_status(self):
        """Returns (total, dirty_or_missing_count)."""
        total = len(self.image_files)
        
        with self._preview_generation_lock:
            dirty = set(self.preview_dirty)
        
        missing = 0
        for idx in range(total):
            landscape_file = self.preview_landscape_folder / f"{idx + 1:04d}.jpg"
            portrait_file = self.preview_portrait_folder / f"{idx + 1:04d}.jpg"
            if not landscape_file.exists() or not portrait_file.exists():
                missing += 1
        
        need_count = len(dirty) + missing
        if need_count > 0:
            print(f"[PREVIEW] need_count={need_count} (dirty={len(dirty)}, missing={missing})")
        return (total, need_count)
    
    def prepare_all_previews_async(self, progress_callback=None):
        """Generate all missing previews in background thread. Thread-safe."""
        def create_placeholder(folder, idx):
            output_name = f"{idx + 1:04d}.jpg"
            output_path = folder / output_name
            placeholder = np.zeros((100, 100, 3), dtype=np.uint8)
            cv2.imwrite(str(output_path), placeholder, [cv2.IMWRITE_JPEG_QUALITY, 50])
        
        def background_task():
            total = len(self.image_files)
            processed = 0
            consecutive_failures = 0
            max_consecutive_failures = 3
            
            print(f"[PREVIEW] Starting background_task for {total} images")
            
            for idx in range(total):
                img_name = self.image_files[idx].name if idx < len(self.image_files) else "?"
                
                # Skip if preview files already exist
                landscape_file = self.preview_landscape_folder / f"{idx + 1:04d}.jpg"
                portrait_file = self.preview_portrait_folder / f"{idx + 1:04d}.jpg"
                if landscape_file.exists() and portrait_file.exists():
                    print(f"[PREVIEW] [{idx+1}/{total}] {img_name}: Skipping - previews exist")
                    processed += 1
                    if progress_callback:
                        progress_callback(processed, total, img_name)
                    continue
                
                print(f"[PREVIEW] [{idx+1}/{total}] Processing: {img_name}")
                
                # Safety: skip if too many consecutive failures
                if consecutive_failures >= max_consecutive_failures:
                    print(f"[PREVIEW] Warning: Too many consecutive failures, stopping at image {idx + 1}")
                    break
                
                if self._cancel_preview_generation:
                    print(f"[PREVIEW] {img_name}: cancelled, skipping")
                    with self._preview_generation_lock:
                        self.preview_dirty.discard(idx)
                    continue
                
                focal = None
                with self._preview_generation_lock:
                    focal = self.focal_points.get(idx)
                
                print(f"[PREVIEW] {img_name}: focal={focal}")
                
                if focal is None:
                    print(f"[PREVIEW] {img_name}: No focal, loading image...")
                    img, load_method = load_image_safely(self.image_files[idx])
                    if img is not None:
                        h, w = img.shape[:2]
                        focal = (w / 2, h / 2)
                        with self._preview_generation_lock:
                            self.focal_points[idx] = focal
                            self.auto_center_flags[idx] = True
                        consecutive_failures = 0
                        print(f"[PREVIEW] {img_name}: Auto-centered at {focal}")
                    else:
                        print(f"[PREVIEW] {img_name}: Failed to load, skipping")
                        with self._preview_generation_lock:
                            self.preview_dirty.discard(idx)
                        consecutive_failures += 1
                        continue
                
                if focal is None:
                    print(f"[PREVIEW] {img_name}: Still no focal, skipping")
                    with self._preview_generation_lock:
                        self.preview_dirty.discard(idx)
                    consecutive_failures += 1
                    continue
                
                if self._cancel_preview_generation:
                    print(f"[PREVIEW] {img_name}: cancelled before alignment, skipping")
                    with self._preview_generation_lock:
                        self.preview_dirty.discard(idx)
                    continue
                
                consecutive_failures = 0
                
                print(f"[PREVIEW] {img_name}: Aligning landscape...")
                try:
                    success = self._align_single_image_threaded(
                        idx, self.image_files[idx], focal,
                        self.preview_landscape_folder, "landscape", timeout=30)
                    if not success:
                        print(f"[PREVIEW] {img_name}: Landscape skipped due to timeout/error")
                except Exception as e:
                    print(f"[PREVIEW] {img_name}: Landscape error: {e}")
                
                print(f"[PREVIEW] {img_name}: Checking cancel after landscape...")
                if self._cancel_preview_generation:
                    print(f"[PREVIEW] {img_name}: cancelled after landscape, skipping portrait")
                    with self._preview_generation_lock:
                        self.preview_dirty.discard(idx)
                    continue
                
                print(f"[PREVIEW] {img_name}: Aligning portrait...")
                try:
                    success = self._align_single_image_threaded(
                        idx, self.image_files[idx], focal,
                        self.preview_portrait_folder, "portrait", timeout=30)
                    if not success:
                        print(f"[PREVIEW] {img_name}: Portrait skipped due to timeout/error")
                except Exception as e:
                    print(f"[PREVIEW] {img_name}: Portrait error: {e}")
                
                print(f"[PREVIEW] {img_name}: Marking complete...")
                with self._preview_generation_lock:
                    self.preview_dirty.discard(idx)
                
                processed += 1
                print(f"[PREVIEW] {img_name}: Done, processed={processed}")
                
                if progress_callback:
                    img_name = self.image_files[idx].name if idx < len(self.image_files) else ""
                    progress_callback(processed, total, img_name)
            
            print(f"[PREVIEW] Loop complete, saving focal points...")
            self.save_focal_points()
            print(f"[PREVIEW] Saving complete, calling final callback...")
            if progress_callback:
                progress_callback(-1, total, "")
            print(f"[PREVIEW] Finished")
        
        self._cancel_preview_generation = False
        thread = threading.Thread(target=background_task)
        thread.daemon = True
        thread.start()
    
    def cancel_preview_generation(self):
        """Cancel ongoing preview generation."""
        self._cancel_preview_generation = True
    
    def confirm_and_save(self):
        """Save current focal point and generate aligned images."""
        if self.current_idx not in self.focal_points:
            img = self.get_current_image()
            if img is not None:
                h, w = img.shape[:2]
                self.focal_points[self.current_idx] = (w / 2, h / 2)
                self.image_dimensions[self.current_idx] = (w, h)
                self.auto_center_flags[self.current_idx] = True
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
        """Align a single image with given focal point to specified orientation.
        
        Returns True if successful, False otherwise.
        """
        try:
            if focal is None:
                img, load_method = load_image_safely(img_file)
                if img is not None:
                    h, w = img.shape[:2]
                    focal = (w / 2, h / 2)
                else:
                    return False
            
            if orientation == "portrait":
                target_w = self.target_height
                target_h = self.target_width
            else:
                target_w = self.target_width
                target_h = self.target_height
            
            img, load_method = load_image_safely(img_file)
            if img is None:
                return False
            
            h, w = img.shape[:2]
            focal_x, focal_y = focal
            
            crop_x, crop_y, scale, crop_w, crop_h = calculate_transformation(
                focal_x, focal_y, w, h, target_w, target_h
            )
            
            scaled_w = int(w * scale)
            scaled_h = int(h * scale)
            scaled = cv2.resize(img, (scaled_w, scaled_h), interpolation=cv2.INTER_LANCZOS4)
            
            src_x = max(0, int(round(crop_x)))
            src_y = max(0, int(round(crop_y)))
            
            actual_crop_h = min(src_y + int(round(crop_h)), scaled_h)
            actual_crop_w = min(src_x + int(round(crop_w)), scaled_w)
            
            src_h = actual_crop_h - src_y
            src_w = actual_crop_w - src_x
            
            aligned = scaled[src_y:src_y + src_h, src_x:src_x + src_w]
            
            if aligned.shape[0] != target_h or aligned.shape[1] != target_w:
                aligned = cv2.resize(aligned, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
            
            output_folder.mkdir(parents=True, exist_ok=True)
            output_name = f"{idx + 1:04d}.jpg"
            output_path = output_folder / output_name
            cv2.imwrite(str(output_path), aligned, [cv2.IMWRITE_JPEG_QUALITY, 90])
            return True
        except Exception:
            return False
    
    def _align_single_image_threaded(self, idx, img_file, focal, output_folder, orientation, timeout=30):
        """Wrapper to run align_single_image with timeout in a background thread."""
        result = {'success': True, 'error': None}
        
        def target():
            try:
                print(f"[THREAD] Starting align_single_image for {img_file.name} ({orientation})")
                self.align_single_image(idx, img_file, focal, output_folder, orientation)
                print(f"[THREAD] Completed align_single_image for {img_file.name} ({orientation})")
            except Exception as e:
                result['error'] = str(e)
                print(f"[THREAD] Exception in align_single_image for {img_file.name}: {e}")
        
        print(f"[THREAD] Starting thread for {img_file.name} ({orientation})...")
        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()
        print(f"[THREAD] Waiting for thread to complete (timeout={timeout}s)...")
        thread.join(timeout)
        
        if thread.is_alive():
            print(f"[THREAD] WARNING: Thread timed out for {img_file.name} ({orientation})")
            result['success'] = False
        elif result['error']:
            print(f"[THREAD] Error in thread for {img_file.name}: {result['error']}")
            result['success'] = False
        else:
            print(f"[THREAD] Thread succeeded for {img_file.name} ({orientation})")
        
        return result['success']
    
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
                img, load_method = load_image_safely(img_file)
                if img is not None:
                    h, w = img.shape[:2]
                    current_focal = (w / 2, h / 2)
                    self.focal_points[idx] = current_focal
                    self.auto_center_flags[idx] = True
            
            if current_focal is not None:
                self.align_single_image(idx, img_file, current_focal, folder, orientation)
        
        self.save_focal_points()
    
    def ensure_preview_for_current(self, orientation="landscape"):
        """Ensure preview exists for current image, generating if needed."""
        folder = self.preview_landscape_folder if orientation == "landscape" else self.preview_portrait_folder
        filename = f"{self.current_idx + 1:04d}.jpg"
        preview_path = folder / filename
        
        with self._preview_generation_lock:
            is_dirty = self.current_idx in self.preview_dirty
        
        if preview_path.exists() and not is_dirty:
            return True
        
        current_focal = self.focal_points.get(self.current_idx)
        if current_focal is None:
            img = self.get_current_image()
            if img is not None:
                h, w = img.shape[:2]
                current_focal = (w / 2, h / 2)
                self.focal_points[self.current_idx] = current_focal
                self.auto_center_flags[self.current_idx] = True
        
        if current_focal is not None:
            success = self.align_single_image(
                self.current_idx,
                self.image_files[self.current_idx],
                current_focal,
                folder,
                orientation
            )
            with self._preview_generation_lock:
                self.preview_dirty.discard(self.current_idx)
            self.save_focal_points()
            return success
        return False
    
    def navigate(self, direction):
        """Navigate to previous/next image."""
        new_idx = self.current_idx + direction
        if 0 <= new_idx < len(self.image_files):
            self.current_idx = new_idx
            return True
        return False
    
    def navigate_wrap(self, direction):
        """Navigate with wrapping (for preview mode)."""
        if not self.image_files:
            return False
        self.current_idx = (self.current_idx + direction) % len(self.image_files)
        return True
    
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

    def move_image(self, from_index, to_index):
        """Move image from from_index to to_index, shifting other images accordingly."""
        if from_index == to_index or not (0 <= from_index < len(self.image_files)) or not (0 <= to_index < len(self.image_files)):
            return False
        
        # Move the image file
        self.image_files.insert(to_index, self.image_files.pop(from_index))
        
        # Adjust indices if we moved an item before another
        if to_index < from_index:
            to_index += 1  # Compensate for the removal shifting indices down
        
        # Update focal points dictionary
        if from_index in self.focal_points:
            focal_value = self.focal_points.pop(from_index)
            self.focal_points[to_index] = focal_value
        
        # Update completed set
        if from_index in self.completed:
            self.completed.remove(from_index)
            self.completed.add(to_index)
        
        # Update auto_center_flags
        if from_index in self.auto_center_flags:
            flag_value = self.auto_center_flags.pop(from_index)
            self.auto_center_flags[to_index] = flag_value
        
        # Update image_dimensions
        if from_index in self.image_dimensions:
            dims_value = self.image_dimensions.pop(from_index)
            self.image_dimensions[to_index] = dims_value
        
        # Update current index if it was affected by the move
        if self.current_idx == from_index:
            self.current_idx = to_index
        elif self.current_idx == to_index and from_index < to_index:
            self.current_idx -= 1
        elif self.current_idx > from_index and self.current_idx <= to_index:
            self.current_idx -= 1
        elif self.current_idx >= to_index and self.current_idx < from_index:
            self.current_idx += 1
        
        # Save changes
        self.save_focal_points()
        return True

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
        if self.current_idx in self.auto_center_flags:
            del self.auto_center_flags[self.current_idx]
        
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
        self.auto_center_flags.clear()
        
        if self.json_path.exists():
            self.json_path.unlink()
        
        for folder in [self.preview_landscape_folder, self.preview_portrait_folder]:
            if folder and folder.exists():
                shutil.rmtree(folder)
        
        self.current_idx = 0
        self.alignment_mode = None
        self.save_focal_points()
    
    def cleanup_preview_folders(self):
        """Remove preview folders after final export."""
        for folder in [self.preview_landscape_folder, self.preview_portrait_folder]:
            if folder and folder.exists():
                shutil.rmtree(folder)
    
    def get_preview_folder(self, orientation="landscape"):
        """Get the preview folder for the given orientation."""
        return self.preview_landscape_folder if orientation == "landscape" else self.preview_portrait_folder
    
    def is_preview_ready(self, orientation="landscape"):
        """Check if preview folder has all images generated."""
        folder = self.get_preview_folder(orientation)
        if not folder or not folder.exists():
            return False
        
        expected_count = len(self.image_files)
        existing_count = len(list(folder.glob("*.jpg")))
        return existing_count == expected_count
    
    def get_preview_image_count(self, orientation="landscape"):
        """Get count of existing preview images."""
        folder = self.get_preview_folder(orientation)
        if not folder or not folder.exists():
            return 0
        return len(list(folder.glob("*.jpg")))
    
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
        return self.is_focal_at_center_idx(self.current_idx)
    
    def is_focal_at_center_idx(self, idx):
        """Check if focal point at given index is at image center."""
        focal = self.focal_points.get(idx)
        dims = self.image_dimensions.get(idx)
        if focal and dims:
            center_x = dims[0] / 2
            center_y = dims[1] / 2
            return abs(focal[0] - center_x) <= 1 and abs(focal[1] - center_y) <= 1
        return False