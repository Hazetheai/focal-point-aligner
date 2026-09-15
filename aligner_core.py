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
    from ui.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
import numpy as np

JSON_VERSION = "2.0"

# Sensible framing for any image size. Tweak these if output framing feels wrong;
# they are documented in README.md and AGENTS.md.
DEFAULT_MAX_ZOOM = 3.0  # slider default (range 1.0-6.0); cap = cover * this
UPSCALE_CAP = 2.0       # max real upscale of the sharp subject before blur-fill
THUMB_MAX = 512
CACHE_DIR_NAME = ".fpa_cache"
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}


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


def compute_crop(focal_x, focal_y, orig_w, orig_h, target_w, target_h, max_zoom=DEFAULT_MAX_ZOOM):
    """Return (x, y, w, h) crop rectangle in original pixels.

    The focal point is centered in the output frame (clamped at the edges).
    Large sources: take a 1:1 crop of the target size. Small sources: scale
    up just enough to cover the frame. `max_zoom` is unused (kept for callers).
    """
    del max_zoom
    orig_w = float(orig_w)
    orig_h = float(orig_h)
    target_w = float(target_w)
    target_h = float(target_h)
    cover = max(target_w / orig_w, target_h / orig_h) if orig_w and orig_h else 1.0
    scale = max(cover, 1.0)
    w = min(orig_w, max(1.0, target_w / scale))
    h = min(orig_h, max(1.0, target_h / scale))
    fx = max(0.0, min(float(focal_x), orig_w))
    fy = max(0.0, min(float(focal_y), orig_h))
    x = min(max(fx - w / 2, 0.0), orig_w - w)
    y = min(max(fy - h / 2, 0.0), orig_h - h)
    return (int(round(x)), int(round(y)), int(round(w)), int(round(h)))


def render_aligned(img, focal, target_w, target_h, max_zoom=DEFAULT_MAX_ZOOM):
    """Render one image to exactly (target_h, target_w).

    Crops around the focal point, then scales to the target size. Small
    sources are upscaled; large sources keep native pixels in the crop.
    """
    h, w = img.shape[:2]
    if focal is None:
        focal = (w / 2, h / 2)
    fx, fy = focal
    x, y, cw, ch = compute_crop(fx, fy, w, h, target_w, target_h, max_zoom)
    region = img[y:y + ch, x:x + cw]
    aligned = cv2.resize(region, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
    return aligned, False


def crop_to_widget(crop_x, crop_y, crop_w, crop_h, img_x, img_y, disp_w, disp_h, orig_w, orig_h):
    """Map an original-pixel crop rect to widget display coordinates (pure helper)."""
    sx = disp_w / orig_w if orig_w else 1.0
    sy = disp_h / orig_h if orig_h else 1.0
    wx = img_x + crop_x * sx
    wy = img_y + crop_y * sy
    ww = crop_w * sx
    wh = crop_h * sy
    return (int(round(wx)), int(round(wy)), int(round(ww)), int(round(wh)))


def _exif_orientation(img_path):
    if not PIL_AVAILABLE:
        return 1
    try:
        with Image.open(str(img_path)) as im:
            return int(im.getexif().get(0x0112, 1) or 1)
    except Exception:
        return 1


def _transpose_hw(img):
    if img.ndim == 3:
        return np.ascontiguousarray(np.transpose(img, (1, 0, 2)))
    return np.ascontiguousarray(np.transpose(img, (1, 0)))


def _apply_exif_orientation(img, orientation):
    """Rotate/flip a BGR array so it matches browser (and PIL) display orientation."""
    orientation = int(orientation or 1)
    if orientation == 2:
        return cv2.flip(img, 1)
    if orientation == 3:
        return cv2.rotate(img, cv2.ROTATE_180)
    if orientation == 4:
        return cv2.flip(img, 0)
    if orientation == 5:
        return _transpose_hw(img)
    if orientation == 6:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if orientation == 7:
        return cv2.flip(_transpose_hw(img), 1)
    if orientation == 8:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def load_image_safely(img_path):
    """Load an image using OpenCV, with PIL fallback. Honors EXIF orientation."""
    orientation = _exif_orientation(img_path)
    img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
    if img is not None and img.size > 0:
        if img.ndim == 3 and img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return _apply_exif_orientation(img, orientation), "opencv"

    if not PIL_AVAILABLE:
        return None, "failed"

    try:
        with Image.open(str(img_path)) as pil_img:
            oriented = ImageOps.exif_transpose(pil_img)
            if oriented is not None:
                pil_img = oriented
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            return img, "pil"
    except Exception:
        return None, "failed"


def _exif_float(value):
    """Coerce an EXIF rational / int / tuple into a float, or None."""
    if value is None:
        return None
    try:
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            den = float(value.denominator)
            return float(value.numerator) / den if den else None
        if isinstance(value, (tuple, list)) and value:
            if len(value) >= 2 and value[1]:
                return float(value[0]) / float(value[1])
            return float(value[0])
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def probe_image_meta(img_path):
    """Header-only image facts: size, DPI, format, mode, file size.

    Size follows EXIF orientation so it matches the displayed / OpenCV pixels.
    """
    path = Path(img_path)
    try:
        nbytes = path.stat().st_size if path.exists() else 0
    except OSError:
        nbytes = 0
    meta = {
        "width": 0,
        "height": 0,
        "bytes": nbytes,
        "format": (path.suffix.lstrip(".") or None),
        "mode": None,
        "dpi": None,
        "orientation": 1,
    }
    if PIL_AVAILABLE:
        try:
            with Image.open(str(path)) as im:
                w, h = im.size
                orientation = int(im.getexif().get(0x0112, 1) or 1)
                if orientation in (5, 6, 7, 8):
                    w, h = h, w
                meta["width"] = int(w)
                meta["height"] = int(h)
                meta["format"] = (im.format or meta["format"] or "").lower() or None
                meta["mode"] = im.mode
                meta["orientation"] = orientation
                dpi = im.info.get("dpi")
                if dpi:
                    dx = _exif_float(dpi[0] if isinstance(dpi, (tuple, list)) else dpi)
                    dy = _exif_float(dpi[1] if isinstance(dpi, (tuple, list)) and len(dpi) > 1 else dx)
                    if dx:
                        meta["dpi"] = [round(dx, 2), round(dy or dx, 2)]
                if meta["dpi"] is None:
                    exif = im.getexif()
                    dx = _exif_float(exif.get(282))
                    dy = _exif_float(exif.get(283))
                    unit = int(exif.get(296) or 2)
                    if dx:
                        if unit == 3:  # pixels per cm
                            dx, dy = dx * 2.54, (dy or dx) * 2.54
                        meta["dpi"] = [round(dx, 2), round((dy or dx), 2)]
                if meta["width"] > 0 and meta["height"] > 0:
                    return meta
        except Exception:
            pass
    img, _ = load_image_safely(img_path)
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return None
    meta["width"] = int(w)
    meta["height"] = int(h)
    return meta


def probe_image_size(img_path):
    """Return (width, height) from file headers without decoding pixels.

    Uses EXIF orientation so the size matches what a browser displays.
    Falls back to a full decode only if the header probe fails.
    """
    meta = probe_image_meta(img_path)
    if not meta:
        return None
    return (meta["width"], meta["height"])


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
        self.max_zoom = config.get('max_zoom', DEFAULT_MAX_ZOOM)
        
        self.cache_root = self.input_folder / CACHE_DIR_NAME
        self.thumb_folder = self.cache_root / "thumbs"
        self.preview_cache_folder = self.cache_root / "previews"
        # Legacy sibling preview folders (kept as aliases; new writes go to cache).
        self.preview_landscape_folder = self.preview_cache_folder
        self.preview_portrait_folder = self.preview_cache_folder
        
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
        
        extensions = IMAGE_EXTENSIONS
        self.image_files = sorted([
            f for f in self.input_folder.iterdir()
            if f.is_file() and f.suffix.lower() in extensions
        ])
        
        self.invalid_images = set()
        self.image_dimensions = {}
        self.image_meta = {}
        self._validate_and_discard_images()
        
        if not self.image_files:
            raise ValueError(f"No images found in {self.input_folder}")
        
        self.current_idx = 0
        self.focal_points = {}
        self.completed = set()
        self.auto_center_flags = {}
        
        self.preview_dirty = set()
        self._cancel_preview_generation = False
        self._preview_generation_lock = threading.Lock()
        
        self.load_focal_points()
        
        if self.image_files:
            for idx, img_file in enumerate(self.image_files):
                if not self.preview_path(img_file, "landscape").exists():
                    self.preview_dirty.add(idx)
            w, h = self.image_dimensions.get(0, (2560, 1440))
            self.ref_w, self.ref_h = w, h
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
                
                if "current_idx" in data:
                    self.current_idx = data["current_idx"]
                    self._current_idx_loaded = True
                
                focal_data = {k: v for k, v in data.items() 
                              if k not in ["alignment_mode", "preview_state", "discarded", "current_idx", "order", "_meta"]}
                
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
                
                if "order" in data and isinstance(data["order"], list):
                    self._reorder_files_by_names(data["order"])
                
                if self.focal_points:
                    # Only set first_pending if current_idx was NOT loaded from JSON
                    if not hasattr(self, '_current_idx_loaded'):
                        first_pending = 0
                        for i in range(len(self.image_files)):
                            if i not in self.completed:
                                first_pending = i
                                break
                        else:
                            first_pending = len(self.image_files) - 1
                        self.current_idx = first_pending
                else:
                    # No focal points, start at 0
                    self.current_idx = 0
            except Exception as e:
                logger.warning(f"Warning: Could not load focal points: {e}")
    
    def _reorder_files_by_names(self, ordered_names):
        """Reorder self.image_files to match a persisted order list (by filename).

        Filenames no longer present are skipped; files not listed (e.g. newly added)
        are appended in sorted order. All per-index dicts are remapped by filename.
        """
        if not ordered_names:
            return
        by_name = {f.name: f for f in self.image_files}
        
        ordered = []
        for name in ordered_names:
            if name in by_name:
                ordered.append(by_name.pop(name))
        ordered.extend(sorted(by_name.values()))
        
        if len(ordered) != len(self.image_files):
            logger.warning(f"[ALIGNER _reorder_files_by_names] Length mismatch: order={len(ordered)} vs files={len(self.image_files)}")
            return
        
        old_name_to_idx = {f.name: i for i, f in enumerate(self.image_files)}
        name_to_new_idx = {f.name: i for i, f in enumerate(ordered)}
        
        new_focal = {}
        new_completed = set()
        new_auto_center = {}
        new_dimensions = {}
        for new_idx, img_file in enumerate(ordered):
            old_idx = old_name_to_idx[img_file.name]
            if old_idx in self.focal_points:
                new_focal[new_idx] = self.focal_points[old_idx]
            if old_idx in self.completed:
                new_completed.add(new_idx)
            if old_idx in self.auto_center_flags:
                new_auto_center[new_idx] = self.auto_center_flags[old_idx]
            if old_idx in self.image_dimensions:
                new_dimensions[new_idx] = self.image_dimensions[old_idx]
        
        self.image_files = ordered
        self.focal_points = new_focal
        self.completed = new_completed
        self.auto_center_flags = new_auto_center
        self.image_dimensions = new_dimensions
        logger.info(f"[ALIGNER _reorder_files_by_names] Reordered to {[f.name[:20] for f in ordered[:5]]}...")
    
    def _validate_and_discard_images(self):
        """Validate images via header probe; move undecodable files aside.

        Stores original (width, height) in image_dimensions without a full decode.
        """
        if not self.image_files:
            return
        
        invalid_indices = []
        
        for idx, img_file in enumerate(self.image_files):
            meta = probe_image_meta(img_file)
            if meta is None:
                logger.warning(f"[VALIDATE] Invalid image (cannot probe): {img_file.name}")
                invalid_indices.append(idx)
                self.invalid_images.add(img_file.name)
                continue
            self.image_dimensions[idx] = (meta["width"], meta["height"])
            self.image_meta[img_file.name] = meta
        
        if not invalid_indices:
            logger.info(f"[VALIDATE] All {len(self.image_files)} images are valid")
            return
        
        logger.info(f"[VALIDATE] Found {len(invalid_indices)} invalid images, moving to discarded/invalid/")
        
        invalid_folder = self.input_folder / "discarded" / "invalid"
        invalid_folder.mkdir(parents=True, exist_ok=True)
        
        for idx in reversed(invalid_indices):
            img_file = self.image_files[idx]
            dest = invalid_folder / img_file.name
            if img_file.exists():
                shutil.move(str(img_file), str(dest))
                logger.info(f"[VALIDATE] Moved invalid image to: {dest}")
        
        valid = []
        new_dims = {}
        new_i = 0
        for i, f in enumerate(self.image_files):
            if i in invalid_indices:
                continue
            valid.append(f)
            if i in self.image_dimensions:
                new_dims[new_i] = self.image_dimensions[i]
            new_i += 1
        self.image_files = valid
        self.image_dimensions = new_dims
        
        logger.info(f"[VALIDATE] After validation: {len(self.image_files)} valid images remain")
    
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
        },
            "current_idx": self.current_idx,
        }
        
        data["order"] = [self.image_files[i].name for i in range(len(self.image_files))]
        
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
            logger.warning(f"Warning: Could not save focal points: {e}")
    
    def delete_focal_points_file(self):
        """Delete the focal points JSON file."""
        if self.json_path.exists():
            try:
                self.json_path.unlink()
            except Exception as e:
                logger.warning(f"Warning: Could not delete focal points file: {e}")

    def _ensure_dims(self, idx):
        """Return (w, h) for idx, probing the file header if unknown."""
        dims = self.image_dimensions.get(idx)
        if dims and dims[0] > 0 and dims[1] > 0:
            return dims
        if 0 <= idx < len(self.image_files):
            meta = probe_image_meta(self.image_files[idx])
            if meta:
                size = (meta["width"], meta["height"])
                self.image_dimensions[idx] = size
                self.image_meta[self.image_files[idx].name] = meta
                return size
        return None

    def thumb_path(self, img_file):
        return self.thumb_folder / f"{Path(img_file).stem}.jpg"

    def preview_path(self, img_file, orientation="landscape"):
        return self.preview_cache_folder / f"{Path(img_file).stem}_{orientation}.jpg"

    def ensure_thumbnail(self, idx):
        """Write a ~512px JPEG thumb for idx if missing. Returns path or None."""
        if not (0 <= idx < len(self.image_files)):
            return None
        img_file = self.image_files[idx]
        path = self.thumb_path(img_file)
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        if PIL_AVAILABLE:
            try:
                with Image.open(str(img_file)) as im:
                    oriented = ImageOps.exif_transpose(im)
                    if oriented is not None:
                        im = oriented
                    im = im.convert("RGB")
                    im.thumbnail((THUMB_MAX, THUMB_MAX), Image.Resampling.LANCZOS)
                    im.save(str(path), "JPEG", quality=75, optimize=True)
                return path
            except Exception as e:
                logger.warning(f"[THUMB] PIL failed for {img_file.name}: {e}")
        img, _ = load_image_safely(img_file)
        if img is None:
            return None
        h, w = img.shape[:2]
        scale = min(THUMB_MAX / max(w, 1), THUMB_MAX / max(h, 1), 1.0)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(path), small, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return path

    def ensure_thumbnails(self, progress_callback=None):
        """Generate missing thumbs for every image (sequential, cheap)."""
        total = len(self.image_files)
        for idx in range(total):
            self.ensure_thumbnail(idx)
            if progress_callback:
                progress_callback(idx + 1, total, self.image_files[idx].name)

    def session_snapshot(self):
        """JSON-serializable session state for the web API."""
        images = []
        for i, f in enumerate(self.image_files):
            w, h = self.image_dimensions.get(i, (0, 0))
            focal = self.focal_points.get(i)
            meta = self.image_meta.get(f.name)
            if not meta:
                meta = probe_image_meta(f) or {}
                if meta:
                    self.image_meta[f.name] = meta
                    w, h = meta.get("width") or w, meta.get("height") or h
            images.append({
                "id": i,
                "filename": f.name,
                "path": str(f.resolve()),
                "width": w,
                "height": h,
                "bytes": meta.get("bytes") or 0,
                "format": meta.get("format"),
                "mode": meta.get("mode"),
                "dpi": meta.get("dpi"),
                "orientation": meta.get("orientation") or 1,
                "megapixels": round((w * h) / 1_000_000, 2) if w and h else 0,
                "focal": [focal[0], focal[1]] if focal else None,
                "completed": i in self.completed,
                "auto_center": bool(self.auto_center_flags.get(i, False)),
                "focal_at_center": self.is_focal_at_center_idx(i),
            })
        return {
            "images": images,
            "current_idx": self.current_idx,
            "target_width": self.target_width,
            "target_height": self.target_height,
            "max_zoom": self.max_zoom,
            "alignment_mode": self.alignment_mode or "landscape",
            "input_folder": str(self.input_folder.resolve()),
            "output_folder": str(self.output_folder.resolve()),
            "stats": self.get_stats(),
            "total": self.total_images,
            "completed_count": self.completed_count,
        }

    def crop_for(self, idx, orientation=None):
        """Return compute_crop rect for an image index, or None."""
        dims = self._ensure_dims(idx)
        if not dims:
            return None
        w, h = dims
        focal = self.focal_points.get(idx) or (w / 2, h / 2)
        orientation = orientation or self.alignment_mode or "landscape"
        if orientation == "portrait":
            tw, th = self.target_height, self.target_width
        else:
            tw, th = self.target_width, self.target_height
        x, y, cw, ch = compute_crop(
            focal[0], focal[1], w, h, tw, th, self.max_zoom
        )
        return {"x": x, "y": y, "w": cw, "h": ch, "orig_w": w, "orig_h": h,
                "target_w": tw, "target_h": th, "focal": [focal[0], focal[1]]}

    def export_aligned(self, output_folder, orientation="landscape", progress_callback=None):
        """Write aligned JPEGs to output_folder as {idx:04d}.jpg. GUI export path."""
        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)
        self.set_alignment_mode(orientation)
        total = len(self.image_files)
        exported = 0
        for i, img_file in enumerate(self.image_files):
            focal = self.focal_points.get(i)
            if focal is not None:
                ok = self.align_single_image(
                    i, img_file, focal, output_folder, orientation,
                    output_name=f"{i:04d}.jpg",
                )
                if ok:
                    exported += 1
            if progress_callback:
                progress_callback(i + 1, total, img_file.name)
        return exported
    
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
    
    def get_prev_focal(self):
        """Get focal point coordinates for previous image."""
        prev_idx = self.current_idx - 1
        if prev_idx >= 0:
            return self.focal_points.get(prev_idx)
        return None
    
    def get_next_focal(self):
        """Get focal point coordinates for next image."""
        next_idx = self.current_idx + 1
        if next_idx < len(self.image_files):
            return self.focal_points.get(next_idx)
        return None
    
    def get_preview_image(self, orientation="landscape"):
        """Load preview image for current index (filename-keyed cache)."""
        if not (0 <= self.current_idx < len(self.image_files)):
            return None
        preview_path = self.preview_path(self.image_files[self.current_idx], orientation)
        logger.info(f"[get_preview_image] Looking for: {preview_path}, exists={preview_path.exists()}")
        if preview_path.exists():
            return cv2.imread(str(preview_path))
        return None
    
    def set_focal_point(self, x, y, auto_center=False):
        """Set focal point for current image (in original image coordinates)."""
        self._ensure_dims(self.current_idx)
        
        self.focal_points[self.current_idx] = (float(x), float(y))
        self.auto_center_flags[self.current_idx] = auto_center
        self.completed.add(self.current_idx)
        
        with self._preview_generation_lock:
            self.preview_dirty.add(self.current_idx)
        
        focal = (float(x), float(y))
        orientation = self.alignment_mode or "landscape"
        thread = threading.Thread(
            target=self._generate_previews_for_image,
            args=(self.current_idx, focal, orientation)
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
    
    def _generate_previews_for_image(self, idx, focal, orientation=None):
        """Background preview generation for a single image (current orientation only)."""
        orientation = orientation or self.alignment_mode or "landscape"
        if not (0 <= idx < len(self.image_files)):
            return
        self.align_single_image(
            idx, self.image_files[idx], focal, self.preview_cache_folder, orientation,
            output_name=self.preview_path(self.image_files[idx], orientation).name,
        )
        with self._preview_generation_lock:
            self.preview_dirty.discard(idx)
        self.save_focal_points()
    
    def get_preview_generation_status(self):
        """Returns (total, dirty_or_missing_count)."""
        total = len(self.image_files)
        orientation = self.alignment_mode or "landscape"
        
        with self._preview_generation_lock:
            dirty = set(self.preview_dirty)
        
        missing = 0
        for idx, img_file in enumerate(self.image_files):
            if not self.preview_path(img_file, orientation).exists():
                missing += 1
        
        need_count = len(dirty | {i for i in range(total) if not self.preview_path(self.image_files[i], orientation).exists()})
        logger.info(f"[PREVIEW_STATUS] total={total}, dirty={len(dirty)}, missing={missing}, need_count={need_count}")
        return (total, need_count)
    
    def prepare_all_previews_async(self, progress_callback=None):
        """Generate all missing previews in background thread. Thread-safe."""
        def create_placeholder(folder, idx):
            output_name = f"{idx:04d}.jpg"
            output_path = folder / output_name
            placeholder = np.zeros((100, 100, 3), dtype=np.uint8)
            cv2.imwrite(str(output_path), placeholder, [cv2.IMWRITE_JPEG_QUALITY, 50])
        
        def background_task():
            total = len(self.image_files)
            processed = 0
            consecutive_failures = 0
            max_consecutive_failures = 3
            
            logger.info(f"[PREVIEW] Starting background_task for {total} images")
            
            for idx in range(total):
                img_name = self.image_files[idx].name if idx < len(self.image_files) else "?"
                
                # Skip if preview file already exists
                orientation = self.alignment_mode or "landscape"
                dest = self.preview_path(self.image_files[idx], orientation)
                if dest.exists() and idx not in self.preview_dirty:
                    logger.info(f"[PREVIEW] [{idx+1}/{total}] {img_name}: Skipping - preview exists")
                    processed += 1
                    if progress_callback:
                        progress_callback(processed, total, img_name)
                    continue
                
                logger.info(f"[PREVIEW] [{idx+1}/{total}] Processing: {img_name}")
                
                # Safety: skip if too many consecutive failures
                if consecutive_failures >= max_consecutive_failures:
                    logger.warning(f"[PREVIEW] Warning: Too many consecutive failures, stopping at image {idx + 1}")
                    break
                
                if self._cancel_preview_generation:
                    logger.info(f"[PREVIEW] {img_name}: cancelled, skipping")
                    with self._preview_generation_lock:
                        self.preview_dirty.discard(idx)
                    continue
                
                focal = None
                with self._preview_generation_lock:
                    focal = self.focal_points.get(idx)
                
                logger.info(f"[PREVIEW] {img_name}: focal={focal}")
                
                if focal is None:
                    logger.info(f"[PREVIEW] {img_name}: No focal, loading image...")
                    img, load_method = load_image_safely(self.image_files[idx])
                    if img is not None:
                        h, w = img.shape[:2]
                        focal = (w / 2, h / 2)
                        consecutive_failures = 0
                        logger.info(f"[PREVIEW] {img_name}: Using display-only center at {focal}")
                    else:
                        logger.warning(f"[PREVIEW] {img_name}: Failed to load, skipping")
                        with self._preview_generation_lock:
                            self.preview_dirty.discard(idx)
                        consecutive_failures += 1
                        continue
                
                if focal is None:
                    logger.info(f"[PREVIEW] {img_name}: Still no focal, skipping")
                    with self._preview_generation_lock:
                        self.preview_dirty.discard(idx)
                    consecutive_failures += 1
                    continue
                
                if self._cancel_preview_generation:
                    logger.info(f"[PREVIEW] {img_name}: cancelled before alignment, skipping")
                    with self._preview_generation_lock:
                        self.preview_dirty.discard(idx)
                    continue
                
                consecutive_failures = 0
                
                orientation = self.alignment_mode or "landscape"
                dest = self.preview_path(self.image_files[idx], orientation)
                logger.info(f"[PREVIEW] {img_name}: Aligning {orientation}...")
                try:
                    success = self.align_single_image(
                        idx, self.image_files[idx], focal,
                        self.preview_cache_folder, orientation,
                        output_name=dest.name)
                    if not success:
                        logger.info(f"[PREVIEW] {img_name}: {orientation} skipped due to error")
                except Exception as e:
                    logger.warning(f"[PREVIEW] {img_name}: {orientation} error: {e}")
                
                logger.info(f"[PREVIEW] {img_name}: Marking complete...")
                with self._preview_generation_lock:
                    self.preview_dirty.discard(idx)
                
                processed += 1
                logger.info(f"[PREVIEW] {img_name}: Done, processed={processed}")
                
                if progress_callback:
                    img_name = self.image_files[idx].name if idx < len(self.image_files) else ""
                    progress_callback(processed, total, img_name)
            
            logger.info(f"[PREVIEW] Loop complete, saving focal points...")
            self.save_focal_points()
            logger.info(f"[PREVIEW] Saving complete, calling final callback...")
            if progress_callback:
                progress_callback(-1, total, "")
            logger.info(f"[PREVIEW] Finished")
        
        self._cancel_preview_generation = False
        thread = threading.Thread(target=background_task)
        thread.daemon = True
        thread.start()
    
    def cancel_preview_generation(self):
        """Cancel ongoing preview generation."""
        self._cancel_preview_generation = True
    
    def confirm_and_save(self):
        """Save current focal point (JSON only) and advance. No full-res write."""
        if self.current_idx not in self.focal_points:
            dims = self._ensure_dims(self.current_idx)
            if dims:
                w, h = dims
                self.focal_points[self.current_idx] = (w / 2, h / 2)
                self.auto_center_flags[self.current_idx] = True
            else:
                return False
        
        self._ensure_dims(self.current_idx)
        
        if self.current_idx not in self.completed:
            self.completed.add(self.current_idx)
        
        orientation = self.alignment_mode or "landscape"
        focal = self.focal_points[self.current_idx]
        thread = threading.Thread(
            target=self._generate_previews_for_image,
            args=(self.current_idx, focal, orientation),
        )
        thread.daemon = True
        thread.start()
        
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
        
        output_name = f"{self.current_idx:04d}.jpg"
        output_path = self.output_folder / output_name
        cv2.imwrite(str(output_path), aligned, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
    def align_single_image(self, idx, img_file, focal, output_folder, orientation, output_name=None):
        """Align a single image with given focal point to specified orientation.
        
        Returns True if successful, False otherwise.
        """
        # Use swapped dimensions for portrait orientation
        if orientation == "portrait":
            target_w = self.target_height
            target_h = self.target_width
        else:
            target_w = self.target_width
            target_h = self.target_height
        
        if output_name is None:
            output_name = f"{idx:04d}.jpg"
        
        try:
            img, load_method = load_image_safely(img_file)
            if img is None:
                logger.warning(f"[align_single_image] Failed to load {img_file.name}, creating placeholder")
                output_folder.mkdir(parents=True, exist_ok=True)
                output_path = Path(output_folder) / output_name
                placeholder = np.full((target_h, target_w, 3), 128, dtype=np.uint8)
                cv2.imwrite(str(output_path), placeholder, [cv2.IMWRITE_JPEG_QUALITY, 50])
                return True
            
            h, w = img.shape[:2]
            self.image_dimensions[idx] = (w, h)
            if focal is None:
                focal = (w / 2, h / 2)
            
            aligned, _ = render_aligned(
                img, focal, target_w, target_h,
                max_zoom=self.max_zoom,
            )
            
            output_folder = Path(output_folder)
            output_folder.mkdir(parents=True, exist_ok=True)
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
                logger.info(f"[THREAD] Starting align_single_image for {img_file.name} ({orientation})")
                self.align_single_image(idx, img_file, focal, output_folder, orientation)
                logger.info(f"[THREAD] Completed align_single_image for {img_file.name} ({orientation})")
            except Exception as e:
                result['error'] = str(e)
                logger.warning(f"[THREAD] Exception in align_single_image for {img_file.name}: {e}")
        
        logger.info(f"[THREAD] Starting thread for {img_file.name} ({orientation})...")
        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()
        logger.info(f"[THREAD] Waiting for thread to complete (timeout={timeout}s)...")
        thread.join(timeout)
        
        if thread.is_alive():
            logger.warning(f"[THREAD] WARNING: Thread timed out for {img_file.name} ({orientation})")
            result['success'] = False
        elif result['error']:
            logger.warning(f"[THREAD] Error in thread for {img_file.name}: {result['error']}")
            result['success'] = False
        else:
            logger.info(f"[THREAD] Thread succeeded for {img_file.name} ({orientation})")
        
        return result['success']
    
    def prepare_aligned_previews(self, orientation="landscape"):
        """Pre-generate all preview images for the given orientation (filename-keyed)."""
        self.preview_cache_folder.mkdir(parents=True, exist_ok=True)
        self.set_alignment_mode(orientation)
        
        for idx, img_file in enumerate(self.image_files):
            dest = self.preview_path(img_file, orientation)
            if dest.exists() and idx not in self.preview_dirty:
                continue
            current_focal = self.focal_points.get(idx)
            if current_focal is None:
                dims = self._ensure_dims(idx)
                if dims:
                    current_focal = (dims[0] / 2, dims[1] / 2)
            
            if current_focal is not None:
                self.align_single_image(
                    idx, img_file, current_focal, self.preview_cache_folder, orientation,
                    output_name=dest.name,
                )
                self.preview_dirty.discard(idx)
        
        self.save_focal_points()
    
    def ensure_preview_for_current(self, orientation="landscape"):
        """Ensure preview exists for current image, generating if needed."""
        if not (0 <= self.current_idx < len(self.image_files)):
            return False
        preview_path = self.preview_path(self.image_files[self.current_idx], orientation)
        
        with self._preview_generation_lock:
            is_dirty = self.current_idx in self.preview_dirty
        
        logger.info(f"[ensure_preview] idx={self.current_idx}, file={preview_path.name}, exists={preview_path.exists()}, is_dirty={is_dirty}")
        
        if preview_path.exists() and not is_dirty:
            return True
        
        current_focal = self.focal_points.get(self.current_idx)
        if current_focal is None:
            dims = self._ensure_dims(self.current_idx)
            if not dims:
                return False
            # Display-only center; do not persist a focal the user never set.
            current_focal = (dims[0] / 2, dims[1] / 2)
        
        logger.info(f"[ensure_preview] Generating preview for idx={self.current_idx}")
        success = self.align_single_image(
            self.current_idx,
            self.image_files[self.current_idx],
            current_focal,
            self.preview_cache_folder,
            orientation,
            output_name=preview_path.name,
        )
        with self._preview_generation_lock:
            self.preview_dirty.discard(self.current_idx)
        return success
    
    def navigate(self, direction):
        """Navigate to previous/next image."""
        new_idx = self.current_idx + direction
        logger.info(f"[navigate] direction={direction}, current_idx={self.current_idx}, new_idx={new_idx}, total={len(self.image_files)}")
        if 0 <= new_idx < len(self.image_files):
            self.current_idx = new_idx
            logger.info(f"[navigate] setting current_idx={self.current_idx}")
            return True
        logger.info(f"[navigate] navigation failed - out of bounds")
        return False
    
    def navigate_wrap(self, direction):
        """Navigate with wrapping (for preview mode)."""
        if not self.image_files:
            return False
        old_idx = self.current_idx
        self.current_idx = (self.current_idx + direction) % len(self.image_files)
        logger.info(f"[navigate_wrap] direction={direction}, old_idx={old_idx}, new_idx={self.current_idx}")
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
        
        old_files = list(self.image_files)
        old_to_new = {}
        
        new_files = list(old_files)
        file_moved = new_files.pop(from_index)
        new_files.insert(to_index, file_moved)
        
        for new_idx, path in enumerate(new_files):
            for old_idx, old_path in enumerate(old_files):
                if old_path == path:
                    old_to_new[old_idx] = new_idx
                    break
        
        self.image_files = new_files
        
        new_focal = {}
        new_completed = set()
        new_auto_center = {}
        new_dimensions = {}
        
        for old_idx, focal in self.focal_points.items():
            new_idx = old_to_new.get(old_idx, old_idx)
            new_focal[new_idx] = focal
        
        for old_idx in self.completed:
            new_idx = old_to_new.get(old_idx, old_idx)
            new_completed.add(new_idx)
        
        for old_idx, flag in self.auto_center_flags.items():
            new_idx = old_to_new.get(old_idx, old_idx)
            new_auto_center[new_idx] = flag
        
        for old_idx, dims in self.image_dimensions.items():
            new_idx = old_to_new.get(old_idx, old_idx)
            new_dimensions[new_idx] = dims
        
        self.focal_points = new_focal
        self.completed = new_completed
        self.auto_center_flags = new_auto_center
        self.image_dimensions = new_dimensions
        
        old_current = self.current_idx
        self.current_idx = old_to_new.get(old_current, old_current)
        
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
        """Move current image to discarded folder, preserving arrange order."""
        if not (0 <= self.current_idx < len(self.image_files)):
            return
        current_file = self.image_files[self.current_idx]
        discarded_idx = self.current_idx
        stem = current_file.stem
        logger.info(f"[ALIGNER discard_current] START: current_idx={self.current_idx}, total_images={len(self.image_files)}, file={current_file.name}")
        
        discard_folder = self.input_folder / "discarded"
        discard_folder.mkdir(exist_ok=True)
        dest = discard_folder / current_file.name
        shutil.move(str(current_file), str(dest))
        self.discarded.add(current_file.name)
        
        for path in (
            self.thumb_path(current_file),
            self.preview_path(current_file, "landscape"),
            self.preview_path(current_file, "portrait"),
        ):
            if path.exists():
                path.unlink()
        
        def _shift_dict(d):
            out = {}
            for idx, val in d.items():
                if idx < discarded_idx:
                    out[idx] = val
                elif idx > discarded_idx:
                    out[idx - 1] = val
            return out
        
        def _shift_set(s):
            out = set()
            for idx in s:
                if idx < discarded_idx:
                    out.add(idx)
                elif idx > discarded_idx:
                    out.add(idx - 1)
            return out
        
        self.focal_points = _shift_dict(self.focal_points)
        self.auto_center_flags = _shift_dict(self.auto_center_flags)
        self.image_dimensions = _shift_dict(self.image_dimensions)
        self.completed = _shift_set(self.completed)
        self.preview_dirty = _shift_set(self.preview_dirty)
        
        self.image_files.pop(discarded_idx)
        
        if self.current_idx >= len(self.image_files):
            self.current_idx = max(0, len(self.image_files) - 1)
        
        self.save_focal_points()
        logger.info(f"[ALIGNER discard_current] DONE: current_idx={self.current_idx}, total_images={len(self.image_files)}")
    
    def apply_arrange_order(self, display_order):
        """Apply display order (list mapping new position -> original index) to image_files and all dictionaries."""
        if len(display_order) != len(self.image_files):
            logger.warning(f"[ALIGNER apply_arrange_order] Length mismatch: {len(display_order)} vs {len(self.image_files)}")
            return False
        
        logger.info(f"[ALIGNER apply_arrange_order] Applying order: first 5={display_order[:5]}")
        
        new_files = [self.image_files[i] for i in display_order]
        new_focal = {}
        new_completed = set()
        new_auto_center = {}
        new_dimensions = {}
        
        for new_pos, orig_idx in enumerate(display_order):
            if orig_idx in self.focal_points:
                new_focal[new_pos] = self.focal_points[orig_idx]
            if orig_idx in self.completed:
                new_completed.add(new_pos)
            if orig_idx in self.auto_center_flags:
                new_auto_center[new_pos] = self.auto_center_flags[orig_idx]
            if orig_idx in self.image_dimensions:
                new_dimensions[new_pos] = self.image_dimensions[orig_idx]
        
        old_order = [i for i in range(len(self.image_files))]
        if display_order != old_order:
            old_to_new = {orig_idx: new_pos for new_pos, orig_idx in enumerate(display_order)}
            self.image_files = new_files
            self.focal_points = new_focal
            self.completed = new_completed
            self.auto_center_flags = new_auto_center
            self.image_dimensions = new_dimensions
            self.current_idx = old_to_new.get(self.current_idx, 0)
            self.preview_dirty = {
                old_to_new[idx] for idx in self.preview_dirty if idx in old_to_new
            }
            
            logger.info(f"[ALIGNER apply_arrange_order] DONE, new order: {[f.name[:20] for f in self.image_files[:5]]}")
            return True
        else:
            logger.info("[ALIGNER apply_arrange_order] No change needed")
            return True
    
    def verify_and_fix_preview_integrity(self):
        """Ensure preview files are incrementally named 0, 1, 2, ... without gaps."""
        logger.info(f"[ALIGNER verify_and_fix] Starting integrity check for {len(self.image_files)} images")
        
        for orientation in ["landscape", "portrait"]:
            folder = self.preview_landscape_folder if orientation == "landscape" else self.preview_portrait_folder
            if not folder or not folder.exists():
                continue
            
            # First, clean up any stray temp files from previous failed renames
            for f in folder.glob("__temp_*.jpg"):
                logger.warning(f"[ALIGNER verify_and_fix] Deleting stray temp file: {f.name}")
                f.unlink()
            
            # Get all preview files and their indices
            existing_files = {}
            for f in folder.glob("*.jpg"):
                try:
                    idx = int(f.stem)
                    existing_files[idx] = f
                except ValueError:
                    pass
            
            logger.info(f"[ALIGNER verify_and_fix] {orientation}: found indices {sorted(existing_files.keys())}")
            
            # Check for gaps and renumber
            expected_count = len(self.image_files)
            if len(existing_files) != expected_count:
                logger.warning(f"[ALIGNER verify_and_fix] {orientation}: mismatch! have {len(existing_files)}, expected {expected_count}")
            
            # Now verify and fix: indices should be 0, 1, 2, ... up to expected_count-1
            needs_fix = False
            for expected_idx in range(expected_count):
                if expected_idx not in existing_files:
                    logger.warning(f"[ALIGNER verify_and_fix] {orientation}: missing index {expected_idx}")
                    needs_fix = True
                    break
            
            if not needs_fix:
                # Also check if any index is >= expected_count (out of bounds)
                max_idx = max(existing_files.keys()) if existing_files else -1
                if max_idx >= expected_count:
                    logger.warning(f"[ALIGNER verify_and_fix] {orientation}: has index {max_idx} >= {expected_count}")
                    needs_fix = True
            
            if not needs_fix:
                continue
            
            # Fix: rebuild preview files in correct order
            logger.info(f"[ALIGNER verify_and_fix] {orientation}: rebuilding previews...")
            
            # First, collect what's valid
            valid_originals = {}
            for idx, f in existing_files.items():
                if 0 <= idx < expected_count:
                    valid_originals[idx] = f
            
            # Rename to temporary names first (to avoid collisions)
            temp_files = {}
            for idx, f in valid_originals.items():
                temp_name = f"__temp_{idx:04d}.jpg"
                temp_path = folder / temp_name
                f.rename(temp_path)
                temp_files[idx] = temp_path
            
            # Now rename to final correct names
            for idx, temp_path in sorted(temp_files.items()):
                final_name = f"{idx:04d}.jpg"
                final_path = folder / final_name
                logger.info(f"[ALIGNER verify_and_fix] {orientation}: {temp_path.name} -> {final_name}")
                temp_path.rename(final_path)
            
            logger.info(f"[ALIGNER verify_and_fix] {orientation}: done")
    
    def reset_all(self):
        """Reset all focal points and preview images."""
        for idx in list(self.focal_points.keys()):
            del self.focal_points[idx]
        self.completed.clear()
        self.auto_center_flags.clear()
        
        if self.json_path.exists():
            self.json_path.unlink()
        
        self.cleanup_preview_folders()
        
        self.current_idx = 0
        self.alignment_mode = None
        self.save_focal_points()
    
    def cleanup_preview_folders(self):
        """Remove cache/preview folders after export."""
        if self.cache_root.exists():
            shutil.rmtree(self.cache_root)
    
    def _migrate_preview_naming(self):
        """Migrate from 1-based to 0-based preview naming."""
        for orientation in ["landscape", "portrait"]:
            folder = self.preview_landscape_folder if orientation == "landscape" else self.preview_portrait_folder
            if not folder or not folder.exists():
                continue
            
            files = list(folder.iterdir())
            has_1based = any(f.stem.isdigit() and int(f.stem) > 0 for f in files if f.is_file() and f.suffix.lower() == '.jpg')
            
            if not has_1based:
                continue
            
            logger.info(f"[ALIGNER _migrate_preview_naming] Migrating {orientation} folder from 1-based to 0-based naming")
            
            for f in list(folder.iterdir()):
                if f.is_file() and f.suffix.lower() == '.jpg':
                    try:
                        old_num = int(f.stem)
                        new_num = old_num - 1
                        if new_num >= 0:
                            new_name = f"{new_num:04d}.jpg"
                            new_path = folder / new_name
                            logger.info(f"[ALIGNER _migrate_preview_naming] {f.name} -> {new_name}")
                            f.rename(new_path)
                    except ValueError:
                        pass
        
        logger.info(f"[ALIGNER _migrate_preview_naming] DONE")
    
    def _renumber_previews(self, from_index, old_image_count):
        """Shift preview indices down by 1 for all indices >= from_index (0-based)."""
        logger.info(f"[ALIGNER _renumber_previews] from_index={from_index}, old_image_count={old_image_count}")
        
        for orientation in ["landscape", "portrait"]:
            folder = self.preview_landscape_folder if orientation == "landscape" else self.preview_portrait_folder
            if not folder or not folder.exists():
                continue
            
            files_to_rename = []
            for i in range(from_index, old_image_count):
                old_name = f"{i:04d}.jpg"
                old_path = folder / old_name
                if old_path.exists():
                    files_to_rename.append((old_path, i))
            
            files_to_rename.sort(key=lambda x: x[1], reverse=True)
            
            for old_path, idx in files_to_rename:
                new_name = f"{idx:04d}.jpg"
                new_path = folder / new_name
                logger.info(f"[ALIGNER _renumber_previews] {orientation}: {old_path.name} -> {new_name}")
                old_path.rename(new_path)
        
        logger.info(f"[ALIGNER _renumber_previews] DONE")
    
    def get_preview_folder(self, orientation="landscape"):
        """Get the preview cache folder (filename-keyed files live here)."""
        return self.preview_cache_folder
    
    def is_preview_ready(self, orientation="landscape"):
        """Check if preview files exist for every image."""
        if not self.image_files:
            return False
        return all(self.preview_path(f, orientation).exists() for f in self.image_files)
    
    def get_preview_image_count(self, orientation="landscape"):
        """Get count of existing preview images for orientation."""
        return sum(1 for f in self.image_files if self.preview_path(f, orientation).exists())
    
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