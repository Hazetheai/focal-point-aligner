#!/usr/bin/env python3
"""
Core logic for Focal Point Aligner — image processing, focal points, crop, export.
UI-free; used by the FastAPI backend and CLI.
"""

import json
import logging
import math
import shutil
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

import cv2

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
DEFAULT_MAX_ZOOM = 3.0  # session/config compatibility; framing uses crop_scale
UPSCALE_CAP = 2.0       # unused legacy; kept for importers
THUMB_MAX = 512
CACHE_DIR_NAME = ".fpa_cache"
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm', '.hap'}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
DEFAULT_CROP_SCALE = 1.0
KEYFRAME_EASES = ('linear', 'ease-in', 'ease-out', 'ease-in-out')
DEFAULT_KEYFRAME_EASE = 'ease-in-out'
MIN_CROP_SCALE = 0.05   # zoom in vs base framing (~20×)
ARRANGEMENT_SLOT_MAX = 6  # numeric presets 1…6 (plus original)
MAX_CROP_SCALE = 8.0    # zoom out (clamped by image bounds)


def is_video_path(path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def is_image_path(path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def clamp_crop_scale(crop_scale):
    try:
        value = float(crop_scale)
    except (TypeError, ValueError):
        value = DEFAULT_CROP_SCALE
    if not math.isfinite(value):
        value = DEFAULT_CROP_SCALE
    return max(MIN_CROP_SCALE, min(value, MAX_CROP_SCALE))


def max_crop_for_aspect(orig_w, orig_h, target_w, target_h):
    """Largest target-aspect rectangle that fits in the source."""
    aspect = target_w / target_h if target_h else 1.0
    if orig_h <= 0 or orig_w <= 0:
        return 1.0, 1.0
    if (orig_w / orig_h) >= aspect:
        h = float(orig_h)
        w = h * aspect
    else:
        w = float(orig_w)
        h = w / aspect
    return w, h


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


def _crop_scales(focal_x, focal_y, orig_w, orig_h, target_w, target_h, crop_scale):
    """Return (fx, fy, s0, s_req, s_eff, w_fit, h_fit) for framing helpers."""
    eps = 1e-6
    fx = max(eps, min(float(focal_x), orig_w - eps))
    fy = max(eps, min(float(focal_y), orig_h - eps))
    aspect = target_w / target_h if target_h else 1.0

    max_half_w = min(fx, orig_w - fx)
    max_half_h = min(fy, orig_h - fy)
    h_fit = 2.0 * min(max_half_h, max_half_w / aspect)
    h_fit = max(1.0, min(h_fit, orig_h))
    w_fit = h_fit * aspect
    if w_fit > orig_w:
        w_fit = orig_w
        h_fit = w_fit / aspect

    cover = max(target_w / orig_w, target_h / orig_h)
    s0 = max(1.0, cover)
    s_fit = max(target_w / w_fit, target_h / h_fit)
    crop_scale = clamp_crop_scale(crop_scale)
    s_req = s0 / crop_scale
    s_max = s0 / MIN_CROP_SCALE
    s_req = max(s0 / MAX_CROP_SCALE, min(s_req, s_max))
    s_eff = max(s_req, s_fit)
    return fx, fy, s0, s_req, s_eff, w_fit, h_fit


def bake_crop_scale(focal_x, focal_y, orig_w, orig_h, target_w, target_h,
                    crop_scale=DEFAULT_CROP_SCALE):
    """Bake edge-forced magnification into crop_scale when s_eff > s_req."""
    orig_w = float(orig_w)
    orig_h = float(orig_h)
    target_w = float(target_w)
    target_h = float(target_h)
    if orig_w <= 0 or orig_h <= 0 or target_w <= 0 or target_h <= 0:
        return clamp_crop_scale(crop_scale)
    _fx, _fy, s0, s_req, s_eff, _w_fit, _h_fit = _crop_scales(
        focal_x, focal_y, orig_w, orig_h, target_w, target_h, crop_scale,
    )
    if s_eff <= s_req + 1e-9:
        return clamp_crop_scale(crop_scale)
    return clamp_crop_scale(s0 / s_eff)


def compute_crop_frame(focal_x, focal_y, orig_w, orig_h, target_w, target_h,
                       max_zoom=DEFAULT_MAX_ZOOM, crop_scale=DEFAULT_CROP_SCALE):
    """Return requested (x, y, w, h) centered on focal — may extend outside the image.

    Used by the Original overlay so wheel zoom always moves the white box.
    `max_zoom` is unused (kept for callers).
    """
    del max_zoom
    orig_w = float(orig_w)
    orig_h = float(orig_h)
    target_w = float(target_w)
    target_h = float(target_h)
    if orig_w <= 0 or orig_h <= 0 or target_w <= 0 or target_h <= 0:
        return (0, 0, 1, 1)

    fx, fy, _s0, s_req, _s_eff, _w_fit, _h_fit = _crop_scales(
        focal_x, focal_y, orig_w, orig_h, target_w, target_h, crop_scale,
    )
    w = max(1.0, target_w / s_req)
    h = max(1.0, target_h / s_req)
    x = fx - w / 2.0
    y = fy - h / 2.0
    return (int(round(x)), int(round(y)), int(round(w)), int(round(h)))


def compute_crop(focal_x, focal_y, orig_w, orig_h, target_w, target_h,
                 max_zoom=DEFAULT_MAX_ZOOM, crop_scale=DEFAULT_CROP_SCALE):
    """Return effective in-bounds (x, y, w, h) crop for Preview/export.

    Always centered on the focal. Large sources default to a 1:1 target-sized
    crop at crop_scale=1. When the requested frame (see compute_crop_frame)
    would leave the image, the sample shrinks to the largest centered
    target-aspect rect and render_aligned upscales it — never slides along an
    edge. `max_zoom` is unused (kept for callers).
    """
    del max_zoom
    orig_w = float(orig_w)
    orig_h = float(orig_h)
    target_w = float(target_w)
    target_h = float(target_h)
    if orig_w <= 0 or orig_h <= 0 or target_w <= 0 or target_h <= 0:
        return (0, 0, 1, 1)

    fx, fy, _s0, _s_req, s_eff, w_fit, h_fit = _crop_scales(
        focal_x, focal_y, orig_w, orig_h, target_w, target_h, crop_scale,
    )
    w = max(1.0, target_w / s_eff)
    h = max(1.0, target_h / s_eff)
    if w > w_fit + 1e-6 or h > h_fit + 1e-6:
        w, h = w_fit, h_fit

    x = fx - w / 2.0
    y = fy - h / 2.0
    # Numerical safety — size is already capped to stay centered in-bounds.
    x = min(max(x, 0.0), max(0.0, orig_w - w))
    y = min(max(y, 0.0), max(0.0, orig_h - h))
    return (int(round(x)), int(round(y)), int(round(w)), int(round(h)))


def render_aligned(img, focal, target_w, target_h, max_zoom=DEFAULT_MAX_ZOOM,
                   crop_scale=DEFAULT_CROP_SCALE):
    """Render one image to exactly (target_h, target_w).

    Crops around the focal point, then scales to the target size. Small
    sources are upscaled; large sources keep native pixels in the crop.
    """
    h, w = img.shape[:2]
    if focal is None:
        focal = (w / 2, h / 2)
    fx, fy = focal
    x, y, cw, ch = compute_crop(
        fx, fy, w, h, target_w, target_h, max_zoom, crop_scale=crop_scale,
    )
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



def apply_user_flips(img, flip_h=False, flip_v=False):
    """Apply user flips to a BGR image (after EXIF).

    Naming matches axis of reflection (not "which way the image moves"):
    - flip_v (Flip X in the UI): reflect across the X axis → upside down (top ↔ bottom)
    - flip_h (Flip Y in the UI): reflect across the Y axis → mirror (left ↔ right)
    """
    if img is None:
        return None
    flip_h = bool(flip_h)
    flip_v = bool(flip_v)
    if flip_h and flip_v:
        return cv2.flip(img, -1)
    if flip_h:
        return cv2.flip(img, 1)
    if flip_v:
        return cv2.flip(img, 0)
    return img


def transform_focal_for_flips(fx, fy, width, height, flip_h=False, flip_v=False):
    """Map a focal from unflipped EXIF space into flipped image space.

    flip_h = Flip Y (left ↔ right); flip_v = Flip X (upside down).
    """
    fx = float(fx)
    fy = float(fy)
    if flip_h:
        fx = (float(width) - 1.0) - fx
    if flip_v:
        fy = (float(height) - 1.0) - fy
    return fx, fy


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


def _to_uint8_bgr(img):
    """Normalize OpenCV image arrays to 8-bit BGR for JPEG preview/export."""
    if img is None or not getattr(img, "size", 0):
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.ndim == 3:
        channels = img.shape[2]
        if channels == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        elif channels == 2:
            img = cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
        elif channels != 3:
            return None
    else:
        return None

    if img.dtype == np.uint8:
        return img

    arr = img.astype(np.float32, copy=False)
    maxv = float(arr.max()) if arr.size else 0.0
    if maxv <= 0:
        return np.zeros(img.shape[:2] + (3,), dtype=np.uint8)

    if np.issubdtype(img.dtype, np.floating):
        scale = 255.0 if maxv <= 1.0 + 1e-6 else (255.0 / maxv)
    else:
        # 10/12/14/16-bit payloads often live in uint16 containers.
        if maxv <= 255:
            scale = 1.0
        elif maxv <= 1023:
            scale = 255.0 / 1023.0
        elif maxv <= 4095:
            scale = 255.0 / 4095.0
        elif maxv <= 16383:
            scale = 255.0 / 16383.0
        else:
            scale = 255.0 / 65535.0
    return np.clip(arr * scale, 0, 255).astype(np.uint8)


def load_image_safely(img_path):
    """Load an image using OpenCV, with PIL fallback. Honors EXIF orientation.

    Always returns 8-bit BGR (or None). High-bit-depth sources are scaled down
    so preview/export JPEGs are not clipped to near-white.
    """
    orientation = _exif_orientation(img_path)
    img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
    if img is not None and img.size > 0:
        img = _to_uint8_bgr(img)
        if img is not None:
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


def probe_video_meta_ffmpeg(video_path):
    """Probe video via ffprobe (needed for HAP and other OpenCV-hostile codecs)."""
    if not shutil.which("ffprobe"):
        return None
    path = Path(video_path)
    try:
        nbytes = path.stat().st_size if path.exists() else 0
    except OSError:
        nbytes = 0
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,nb_frames,duration,codec_name",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    streams = payload.get("streams") or []
    if not streams:
        return None
    stream = streams[0]
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        return None
    fps = 30.0
    rate = stream.get("r_frame_rate") or "30/1"
    try:
        if "/" in str(rate):
            num, den = str(rate).split("/", 1)
            den_f = float(den) or 1.0
            fps = float(num) / den_f
        else:
            fps = float(rate)
    except (TypeError, ValueError, ZeroDivisionError):
        fps = 30.0
    if not math.isfinite(fps) or fps <= 0:
        fps = 30.0
    frame_count = 0
    try:
        frame_count = int(stream.get("nb_frames") or 0)
    except (TypeError, ValueError):
        frame_count = 0
    duration = None
    for src in (stream.get("duration"), (payload.get("format") or {}).get("duration")):
        try:
            if src is not None:
                duration = float(src)
                break
        except (TypeError, ValueError):
            continue
    if frame_count <= 0 and duration and duration > 0:
        frame_count = max(1, int(round(duration * fps)))
    if frame_count <= 0:
        frame_count = 1
    duration_ms = int(round(1000.0 * frame_count / fps)) if fps > 0 else 0
    codec = (stream.get("codec_name") or path.suffix.lstrip(".") or "mp4").lower()
    return {
        "width": int(width),
        "height": int(height),
        "bytes": nbytes,
        "format": codec,
        "mode": "video",
        "dpi": None,
        "orientation": 1,
        "media_kind": "video",
        "fps": float(fps),
        "frame_count": int(frame_count),
        "duration_ms": duration_ms,
        "decoder": "ffmpeg",
    }


def probe_video_meta(video_path):
    """Probe a video with OpenCV, falling back to ffprobe for HAP / unsupported codecs."""
    path = Path(video_path)
    try:
        nbytes = path.stat().st_size if path.exists() else 0
    except OSError:
        nbytes = 0
    cap = cv2.VideoCapture(str(path))
    if cap.isOpened():
        try:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if width <= 0 or height <= 0:
                ok, frame = cap.read()
                if ok and frame is not None:
                    height, width = frame.shape[:2]
                    frame_count = max(frame_count, 1)
            if width > 0 and height > 0:
                if frame_count <= 0:
                    frame_count = 1
                if not math.isfinite(fps) or fps <= 0:
                    fps = 30.0
                duration_ms = int(round(1000.0 * frame_count / fps)) if fps > 0 else 0
                return {
                    "width": int(width),
                    "height": int(height),
                    "bytes": nbytes,
                    "format": (path.suffix.lstrip(".") or "mp4").lower(),
                    "mode": "video",
                    "dpi": None,
                    "orientation": 1,
                    "media_kind": "video",
                    "fps": float(fps),
                    "frame_count": int(frame_count),
                    "duration_ms": int(duration_ms),
                    "decoder": "opencv",
                }
        finally:
            cap.release()
    return probe_video_meta_ffmpeg(video_path)


def probe_media_meta(path):
    """Probe image or video headers; returns None when undecodable."""
    path = Path(path)
    if is_video_path(path):
        return probe_video_meta(path)
    if is_image_path(path):
        meta = probe_image_meta(path)
        if meta is not None:
            meta = dict(meta)
            meta["media_kind"] = "image"
        return meta
    return None


def extract_video_frame_ffmpeg(path, frame_idx, fps=None, width=None, height=None) -> Optional[np.ndarray]:
    """Decode a single frame with ffmpeg (HAP-safe). Returns BGR uint8 or None."""
    if not ffmpeg_available():
        return None
    path = Path(path)
    frame_idx = max(0, int(frame_idx))

    def _run(c):
        try:
            return subprocess.run(c, capture_output=True, check=False)
        except OSError:
            return None

    meta = None
    if fps is None or not width or not height:
        meta = probe_video_meta_ffmpeg(path) or {}
        fps = float(fps or meta.get("fps") or 30.0)
        width = int(width or meta.get("width") or 0)
        height = int(height or meta.get("height") or 0)

    if width > 0 and height > 0 and fps and fps > 0:
        ss = frame_idx / fps
        seek_cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{ss:.6f}",
            "-i", str(path),
            "-frames:v", "1",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "pipe:1",
        ]
        proc = _run(seek_cmd)
        if proc is not None and proc.returncode == 0 and proc.stdout:
            expected = width * height * 3
            if len(proc.stdout) >= expected:
                arr = np.frombuffer(proc.stdout[:expected], dtype=np.uint8).reshape((height, width, 3))
                return _to_uint8_bgr(arr.copy())

    vf = f"select=eq(n\\,{frame_idx})"
    jpg_cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        "-vf", vf,
        "-vframes", "1",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "pipe:1",
    ]
    proc = _run(jpg_cmd)
    if proc is None or proc.returncode != 0 or not proc.stdout:
        return None
    arr = np.frombuffer(proc.stdout, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    return _to_uint8_bgr(img)


def extract_video_frame(path, frame_idx) -> Optional[np.ndarray]:
    """Return a single video frame as BGR uint8, or None on failure.

    Tries OpenCV first; falls back to ffmpeg (required for HAP and similar codecs).
    """
    path = Path(path)
    frame_idx = max(0, int(frame_idx))
    cap = cv2.VideoCapture(str(path))
    if cap.isOpened():
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, float(frame_idx))
            ok, frame = cap.read()
            if not ok or frame is None or frame.size == 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                for i in range(frame_idx + 1):
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        frame = None
                        break
                    if i == frame_idx:
                        break
            if frame is not None and frame.size > 0:
                return _to_uint8_bgr(frame)
        finally:
            cap.release()
    return extract_video_frame_ffmpeg(path, frame_idx)


def default_video_range(frame_count: int):
    """Return (in_frame, out_frame, work_frame) defaults for a clip."""
    n = max(1, int(frame_count))
    in_f = 0
    out_f = n - 1
    work_f = n // 2
    return in_f, out_f, work_f


def normalize_ease(ease) -> str:
    e = str(ease or DEFAULT_KEYFRAME_EASE).lower().strip()
    return e if e in KEYFRAME_EASES else DEFAULT_KEYFRAME_EASE


def apply_ease(t: float, ease: str = DEFAULT_KEYFRAME_EASE) -> float:
    """Map linear t in [0,1] through a named ease curve."""
    t = max(0.0, min(1.0, float(t)))
    ease = normalize_ease(ease)
    if ease == "linear":
        return t
    if ease == "ease-in":
        return t * t
    if ease == "ease-out":
        return 1.0 - (1.0 - t) * (1.0 - t)
    if t < 0.5:
        return 2.0 * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0


def _normalize_keyframe(kf, in_f=None, out_f=None) -> Optional[dict]:
    if not isinstance(kf, dict):
        return None
    try:
        frame = int(kf.get("frame"))
        fx = float(kf.get("focal_x"))
        fy = float(kf.get("focal_y"))
    except (TypeError, ValueError):
        return None
    if in_f is not None and out_f is not None:
        if frame < int(in_f) or frame > int(out_f):
            return None
    return {
        "frame": frame,
        "focal_x": fx,
        "focal_y": fy,
        "crop_scale": clamp_crop_scale(kf.get("crop_scale", DEFAULT_CROP_SCALE)),
        "ease": normalize_ease(kf.get("ease")),
    }


def normalize_keyframes(raw, in_f=None, out_f=None) -> list:
    """Dedupe by frame (last wins), clamp to [in,out], sort ascending."""
    by_frame = {}
    for item in raw or []:
        kf = _normalize_keyframe(item, in_f=in_f, out_f=out_f)
        if kf is None:
            continue
        by_frame[kf["frame"]] = kf
    return [by_frame[f] for f in sorted(by_frame)]


def interpolate_from_keyframes(keyframes, frame) -> Optional[tuple]:
    """Return (fx, fy, crop_scale) at frame, or None if no keyframes."""
    kfs = normalize_keyframes(keyframes)
    if not kfs:
        return None
    frame = int(frame)
    if frame <= kfs[0]["frame"]:
        k = kfs[0]
        return (k["focal_x"], k["focal_y"], k["crop_scale"])
    if frame >= kfs[-1]["frame"]:
        k = kfs[-1]
        return (k["focal_x"], k["focal_y"], k["crop_scale"])
    for i in range(len(kfs) - 1):
        a, b = kfs[i], kfs[i + 1]
        if a["frame"] <= frame <= b["frame"]:
            span = max(1, b["frame"] - a["frame"])
            t = apply_ease((frame - a["frame"]) / span, a.get("ease"))
            fx = a["focal_x"] + (b["focal_x"] - a["focal_x"]) * t
            fy = a["focal_y"] + (b["focal_y"] - a["focal_y"]) * t
            cs = a["crop_scale"] + (b["crop_scale"] - a["crop_scale"]) * t
            return (fx, fy, clamp_crop_scale(cs))
    k = kfs[-1]
    return (k["focal_x"], k["focal_y"], k["crop_scale"])


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
        
        self.json_path = self.input_folder / "focal_points.json"
        legacy_json = self.output_folder / "focal_points.json"
        # One-time migrate: older sessions wrote focals next to aligned output.
        if not self.json_path.exists() and legacy_json.exists():
            try:
                shutil.copy2(legacy_json, self.json_path)
            except Exception as e:
                logger.warning(f"Could not migrate focal_points.json from output: {e}")
        
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
        
        extensions = MEDIA_EXTENSIONS
        self.image_files = sorted([
            f for f in self.input_folder.iterdir()
            if f.is_file() and f.suffix.lower() in extensions
        ])
        
        self.invalid_images = set()
        self.image_dimensions = {}
        self.image_meta = {}
        self.video_meta = {}  # idx -> {fps, frame_count, duration_ms, ...}
        self.in_frames = {}
        self.out_frames = {}
        self.work_frames = {}
        self.keyframes = {}  # idx -> list[{frame, focal_x, focal_y, crop_scale, ease}]
        self._validate_and_discard_images()
        
        if not self.image_files:
            raise ValueError(f"No media files found in {self.input_folder}")
        
        self.current_idx = 0
        self.focal_points = {}
        self.completed = set()
        self.auto_center_flags = {}
        self.crop_scales = {}
        self.flip_h = {}
        self.flip_v = {}
        
        self.preview_dirty = set()
        self._cancel_preview_generation = False
        self._preview_generation_lock = threading.Lock()

        # Arrangement history: "original" + "1".."9" filename lists
        self.arrangements = {}
        self.arrangement_active = "original"
        self.arrangement_reversed = {}  # slot -> bool (Reverse button lit state)
        self.arrangement_methods = {}  # slot -> "color"|"depth"|"lead"|"faces"|"manual"
        self._arrange_draft = None  # pending manual order while on Arrange tab
        
        self.load_focal_points()
        self._ensure_video_ranges()

        if "original" not in self.arrangements:
            self.arrangements["original"] = [f.name for f in self.image_files]
            self.arrangement_active = "original"
        else:
            self._sync_arrangements_with_files()
        
        if self.image_files:
            for idx, img_file in enumerate(self.image_files):
                if not self.preview_path(img_file, "landscape").exists():
                    self.preview_dirty.add(idx)
            w, h = self.image_dimensions.get(0, (2560, 1440))
            self.ref_w, self.ref_h = w, h
        else:
            self.ref_h, self.ref_w = 1440, 2560
    
    def is_video(self, idx) -> bool:
        if not (0 <= idx < len(self.image_files)):
            return False
        return is_video_path(self.image_files[idx])

    def media_kind(self, idx) -> str:
        return "video" if self.is_video(idx) else "image"

    def _sync_arrangements_with_files(self):
        """Append newly discovered files (e.g. videos) into arrangement slots.

        Persisted `order` / `arrangements.original` from an images-only session
        must pick up media added later without dropping the saved order.
        """
        names = [f.name for f in self.image_files]
        name_set = set(names)
        for slot, slot_names in list(self.arrangements.items()):
            if not isinstance(slot_names, list):
                continue
            kept = [n for n in slot_names if n in name_set]
            missing = [n for n in names if n not in kept]
            if missing or len(kept) != len(slot_names):
                self.arrangements[slot] = kept + missing

    def _ensure_video_ranges(self):
        """Fill/clamp in/out/work frames for every video; re-probe if needed."""
        for idx, img_file in enumerate(self.image_files):
            if not is_video_path(img_file):
                continue
            meta = self.image_meta.get(img_file.name)
            if not meta or not meta.get("frame_count"):
                meta = probe_video_meta(img_file)
                if meta:
                    self.image_meta[img_file.name] = meta
                    self.image_dimensions[idx] = (meta["width"], meta["height"])
            if not meta:
                continue
            self.video_meta[idx] = {
                "fps": float(meta.get("fps") or 30.0),
                "frame_count": int(meta.get("frame_count") or 1),
                "duration_ms": int(meta.get("duration_ms") or 0),
            }
            n = max(1, int(self.video_meta[idx]["frame_count"]))
            din, dout, dwork = default_video_range(n)
            if idx not in self.in_frames:
                self.in_frames[idx] = din
            if idx not in self.out_frames:
                self.out_frames[idx] = dout
            if idx not in self.work_frames:
                self.work_frames[idx] = dwork
            self.in_frames[idx] = max(0, min(int(self.in_frames[idx]), n - 1))
            self.out_frames[idx] = max(self.in_frames[idx], min(int(self.out_frames[idx]), n - 1))
            self.work_frames[idx] = max(
                self.in_frames[idx],
                min(int(self.work_frames[idx]), self.out_frames[idx]),
            )

    def work_frame_for(self, idx) -> int:
        if idx in self.work_frames:
            return int(self.work_frames[idx])
        if idx in self.in_frames:
            return int(self.in_frames[idx])
        return 0

    def load_media_bgr(self, idx, frame_idx=None):
        """Load image pixels or a video frame as BGR uint8."""
        if not (0 <= idx < len(self.image_files)):
            return None
        path = self.image_files[idx]
        if is_video_path(path):
            if frame_idx is None:
                frame_idx = self.work_frame_for(idx)
            return extract_video_frame(path, frame_idx)
        img, _ = load_image_safely(path)
        return img

    def frame_cache_path(self, img_file, frame_idx) -> Path:
        frames_dir = self.cache_root / "frames"
        return frames_dir / f"{Path(img_file).stem}_{int(frame_idx)}.jpg"

    def ensure_frame_jpeg(self, idx, frame_idx=None):
        """Return a cached JPEG path for a video frame (or image itself)."""
        if not (0 <= idx < len(self.image_files)):
            return None
        img_file = self.image_files[idx]
        if not is_video_path(img_file):
            return img_file
        if frame_idx is None:
            frame_idx = self.work_frame_for(idx)
        frame_idx = int(frame_idx)
        path = self.frame_cache_path(img_file, frame_idx)
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = extract_video_frame(img_file, frame_idx)
        if frame is None:
            return None
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return path

    def set_video_range(self, idx, in_frame=None, out_frame=None, work_frame=None):
        """Update in/out/work frames for a video index. Returns True on success."""
        if not self.is_video(idx):
            return False
        self._ensure_video_ranges()
        n = int(self.video_meta.get(idx, {}).get("frame_count") or 1)
        n = max(1, n)
        old_in = int(self.in_frames.get(idx, 0))
        old_out = int(self.out_frames.get(idx, n - 1))
        cur_in = old_in
        cur_out = old_out
        cur_work = int(self.work_frames.get(idx, cur_in))
        if in_frame is not None:
            cur_in = max(0, min(int(in_frame), n - 1))
        if out_frame is not None:
            cur_out = max(0, min(int(out_frame), n - 1))
        if cur_out < cur_in:
            cur_out = cur_in
        if work_frame is not None:
            cur_work = int(work_frame)
        cur_work = max(cur_in, min(cur_work, cur_out))
        prev_work = self.work_frames.get(idx)
        self.in_frames[idx] = cur_in
        self.out_frames[idx] = cur_out
        self.work_frames[idx] = cur_work
        self._clamp_keyframes_to_trim(idx, old_in=old_in, old_out=old_out)
        # Always refresh display focal from keyframes when seeking / trimming so
        # the UI shows that frame's focal — not the last-saved top-level point.
        if self.keyframes_for(idx):
            self._sync_display_focal_from_keyframes(idx)
        if prev_work != cur_work:
            thumb = self.thumb_path(self.image_files[idx])
            if thumb.exists():
                try:
                    thumb.unlink()
                except OSError:
                    pass
            self.preview_dirty.add(idx)
        self.save_focal_points()
        return True


    def _trim_bounds(self, idx):
        n = max(1, int(self.video_meta.get(idx, {}).get("frame_count") or 1))
        din, dout, _ = default_video_range(n)
        in_f = int(self.in_frames.get(idx, din))
        out_f = int(self.out_frames.get(idx, dout))
        return in_f, out_f

    def keyframes_for(self, idx) -> list:
        if not self.is_video(idx):
            return []
        in_f, out_f = self._trim_bounds(idx)
        return normalize_keyframes(self.keyframes.get(idx) or [], in_f=in_f, out_f=out_f)

    def interpolate_focal_at(self, idx, frame=None):
        """Return (fx, fy, crop_scale) at frame for videos with keyframes.

        Falls back to stored focal + crop_scale, then image center.
        """
        self._ensure_dims(idx)
        dims = self.image_dimensions.get(idx, (0, 0))
        w, h = dims[0] or 0, dims[1] or 0
        if frame is None:
            frame = self.work_frame_for(idx) if self.is_video(idx) else 0
        kfs = self.keyframes_for(idx) if self.is_video(idx) else []
        if kfs:
            got = interpolate_from_keyframes(kfs, frame)
            if got is not None:
                return got
        if idx in self.focal_points:
            fx, fy = self.focal_points[idx]
            return (float(fx), float(fy), clamp_crop_scale(self.crop_scales.get(idx, DEFAULT_CROP_SCALE)))
        return (w / 2.0, h / 2.0, clamp_crop_scale(self.crop_scales.get(idx, DEFAULT_CROP_SCALE)))

    def _sync_display_focal_from_keyframes(self, idx):
        """Keep top-level focal/crop_scale aligned with work_frame interpolation."""
        if not self.is_video(idx):
            return
        kfs = self.keyframes_for(idx)
        if not kfs:
            return
        fx, fy, cs = self.interpolate_focal_at(idx, self.work_frame_for(idx))
        self.focal_points[idx] = (fx, fy)
        self.crop_scales[idx] = cs
        self.completed.add(idx)

    def _ensure_endpoint_keyframes(self, idx, fx, fy, crop_scale, ease=None):
        """Guarantee In and Out keyframes exist (copying fx/fy/scale when creating)."""
        if not self.is_video(idx):
            return
        in_f, out_f = self._trim_bounds(idx)
        ease = normalize_ease(ease)
        cs = clamp_crop_scale(crop_scale)
        by_frame = {k["frame"]: dict(k) for k in self.keyframes_for(idx)}
        if in_f not in by_frame:
            by_frame[in_f] = {
                "frame": in_f, "focal_x": float(fx), "focal_y": float(fy),
                "crop_scale": cs, "ease": ease,
            }
        if out_f not in by_frame:
            by_frame[out_f] = {
                "frame": out_f, "focal_x": float(fx), "focal_y": float(fy),
                "crop_scale": cs, "ease": ease,
            }
        self.keyframes[idx] = normalize_keyframes(by_frame.values(), in_f=in_f, out_f=out_f)

    def _clamp_keyframes_to_trim(self, idx, old_in=None, old_out=None):
        """Keep keyframes inside [in,out]; move endpoint KFs with the trim handles."""
        if not self.keyframes.get(idx):
            return
        in_f, out_f = self._trim_bounds(idx)
        raw = list(self.keyframes.get(idx) or [])
        if not raw:
            self.keyframes.pop(idx, None)
            return
        by_frame = {}
        for item in raw:
            kf = _normalize_keyframe(item, in_f=None, out_f=None)
            if kf is None:
                continue
            fr = kf["frame"]
            # Remap former endpoints onto the new In/Out.
            if old_in is not None and fr == int(old_in):
                fr = in_f
            elif old_out is not None and fr == int(old_out):
                fr = out_f
            if fr < in_f or fr > out_f:
                continue
            kf = dict(kf)
            kf["frame"] = fr
            by_frame[fr] = kf
        # Guarantee In/Out endpoint keyframes when any keyframes remain (or after remap).
        if by_frame:
            seed = next(iter(by_frame.values()))
            if in_f not in by_frame:
                by_frame[in_f] = {
                    "frame": in_f,
                    "focal_x": seed["focal_x"],
                    "focal_y": seed["focal_y"],
                    "crop_scale": seed["crop_scale"],
                    "ease": seed["ease"],
                }
            if out_f not in by_frame:
                seed_out = by_frame.get(max(by_frame.keys()), seed)
                by_frame[out_f] = {
                    "frame": out_f,
                    "focal_x": seed_out["focal_x"],
                    "focal_y": seed_out["focal_y"],
                    "crop_scale": seed_out["crop_scale"],
                    "ease": seed_out["ease"],
                }
        self.keyframes[idx] = normalize_keyframes(by_frame.values(), in_f=in_f, out_f=out_f)
        if not self.keyframes[idx]:
            self.keyframes.pop(idx, None)

    def add_or_update_keyframe(self, idx, frame, focal_x, focal_y, crop_scale=None, ease=None, create=True):
        """Upsert a keyframe at frame.

        create=False updates an existing keyframe only (no new mid markers).
        In/Out endpoints are seeded when the clip has no keyframes yet.
        """
        if not self.is_video(idx):
            return False
        self._ensure_dims(idx)
        in_f, out_f = self._trim_bounds(idx)
        frame = max(in_f, min(out_f, int(frame)))
        cs = clamp_crop_scale(
            crop_scale if crop_scale is not None
            else self.crop_scales.get(idx, DEFAULT_CROP_SCALE)
        )
        fx, fy = float(focal_x), float(focal_y)
        ease_v = normalize_ease(ease) if ease is not None else DEFAULT_KEYFRAME_EASE
        existing = self.keyframes_for(idx)
        by_frame = {k["frame"]: dict(k) for k in existing}

        if not existing:
            by_frame[in_f] = {
                "frame": in_f, "focal_x": fx, "focal_y": fy,
                "crop_scale": cs, "ease": ease_v,
            }
            by_frame[out_f] = {
                "frame": out_f, "focal_x": fx, "focal_y": fy,
                "crop_scale": cs, "ease": ease_v,
            }
            if create and frame not in (in_f, out_f):
                by_frame[frame] = {
                    "frame": frame, "focal_x": fx, "focal_y": fy,
                    "crop_scale": cs, "ease": ease_v,
                }
            self.keyframes[idx] = normalize_keyframes(by_frame.values(), in_f=in_f, out_f=out_f)
        else:
            if frame not in by_frame and not create and frame not in (in_f, out_f):
                # Focal save without inventing a mid keyframe.
                self.focal_points[idx] = (fx, fy)
                self.crop_scales[idx] = cs
                self.completed.add(idx)
                self.save_focal_points()
                return True
            prev = by_frame.get(frame) or {}
            by_frame[frame] = {
                "frame": frame,
                "focal_x": fx,
                "focal_y": fy,
                "crop_scale": cs,
                "ease": normalize_ease(ease if ease is not None else prev.get("ease", ease_v)),
            }
            if in_f not in by_frame:
                seed = by_frame[min(by_frame.keys())]
                by_frame[in_f] = {
                    "frame": in_f, "focal_x": seed["focal_x"], "focal_y": seed["focal_y"],
                    "crop_scale": seed["crop_scale"], "ease": seed["ease"],
                }
            if out_f not in by_frame:
                seed = by_frame[max(by_frame.keys())]
                by_frame[out_f] = {
                    "frame": out_f, "focal_x": seed["focal_x"], "focal_y": seed["focal_y"],
                    "crop_scale": seed["crop_scale"], "ease": seed["ease"],
                }
            self.keyframes[idx] = normalize_keyframes(by_frame.values(), in_f=in_f, out_f=out_f)

        self.focal_points[idx] = (fx, fy)
        self.crop_scales[idx] = cs
        self.completed.add(idx)
        self.work_frames[idx] = frame
        self.preview_dirty.add(idx)
        self.save_focal_points()
        return True

    def set_keyframe_ease(self, idx, frame, ease):
        if not self.is_video(idx):
            return False
        in_f, out_f = self._trim_bounds(idx)
        frame = int(frame)
        by_frame = {k["frame"]: dict(k) for k in self.keyframes_for(idx)}
        if frame not in by_frame:
            return False
        by_frame[frame]["ease"] = normalize_ease(ease)
        self.keyframes[idx] = normalize_keyframes(by_frame.values(), in_f=in_f, out_f=out_f)
        self.save_focal_points()
        return True

    def move_keyframe(self, idx, from_frame, to_frame):
        """Retimed mid keyframes only — In/Out stay tied to the trim handles."""
        if not self.is_video(idx):
            return False
        in_f, out_f = self._trim_bounds(idx)
        from_frame = int(from_frame)
        if from_frame == in_f or from_frame == out_f:
            return False
        to_frame = max(in_f + 1 if out_f > in_f else in_f, min(out_f - 1 if out_f > in_f else out_f, int(to_frame)))
        by_frame = {k["frame"]: dict(k) for k in self.keyframes_for(idx)}
        if from_frame not in by_frame:
            return False
        frames = sorted(by_frame.keys())
        pos = frames.index(from_frame)
        lo = frames[pos - 1] + 1 if pos > 0 else in_f + 1
        hi = frames[pos + 1] - 1 if pos < len(frames) - 1 else out_f - 1
        if lo > hi:
            return False
        to_frame = max(lo, min(hi, to_frame))
        kf = by_frame.pop(from_frame)
        kf["frame"] = to_frame
        by_frame[to_frame] = kf
        self.keyframes[idx] = normalize_keyframes(by_frame.values(), in_f=in_f, out_f=out_f)
        if self.work_frames.get(idx) == from_frame:
            self.work_frames[idx] = to_frame
        self._sync_display_focal_from_keyframes(idx)
        self.save_focal_points()
        return True

    def delete_keyframe(self, idx, frame):
        """Delete a mid keyframe. In/Out endpoints cannot be deleted (they are the trim handles)."""
        if not self.is_video(idx):
            return False
        in_f, out_f = self._trim_bounds(idx)
        frame = int(frame)
        if frame == in_f or frame == out_f:
            return False
        by_frame = {k["frame"]: dict(k) for k in self.keyframes_for(idx)}
        if frame not in by_frame:
            return False
        del by_frame[frame]
        remaining = normalize_keyframes(by_frame.values(), in_f=in_f, out_f=out_f)
        if remaining:
            if in_f not in {k["frame"] for k in remaining}:
                seed = remaining[0]
                remaining.insert(0, {
                    "frame": in_f,
                    "focal_x": seed["focal_x"],
                    "focal_y": seed["focal_y"],
                    "crop_scale": seed["crop_scale"],
                    "ease": seed["ease"],
                })
            if out_f not in {k["frame"] for k in remaining}:
                seed = remaining[-1]
                remaining.append({
                    "frame": out_f,
                    "focal_x": seed["focal_x"],
                    "focal_y": seed["focal_y"],
                    "crop_scale": seed["crop_scale"],
                    "ease": seed["ease"],
                })
            self.keyframes[idx] = normalize_keyframes(remaining, in_f=in_f, out_f=out_f)
        else:
            self.keyframes.pop(idx, None)
        self._sync_display_focal_from_keyframes(idx)
        self.preview_dirty.add(idx)
        self.save_focal_points()
        return True

    def _unique_part_path(self, src: Path) -> Path:
        stem, suffix = src.stem, src.suffix
        candidate = self.input_folder / f"{stem}__part2{suffix}"
        n = 3
        while candidate.exists():
            candidate = self.input_folder / f"{stem}__part{n}{suffix}"
            n += 1
        return candidate

    def split_video_at(self, idx, at_frame):
        """Split video at at_frame: part A keeps file with out=at_frame; part B is new file.

        Returns (ok, error_message|None).
        """
        if not self.is_video(idx):
            return False, "Not a video"
        if not ffmpeg_available():
            return False, "ffmpeg not found on PATH — install ffmpeg to split videos"
        src = self.image_files[idx]
        meta = self.video_meta.get(idx) or {}
        n = max(1, int(meta.get("frame_count") or 1))
        fps = float(meta.get("fps") or 30.0)
        at_frame = max(0, min(int(at_frame), n - 1))
        if at_frame >= n - 1:
            return False, "Nothing to split after the last frame"

        dest = self._unique_part_path(src)
        start_frame = at_frame + 1
        start_sec = start_frame / fps if fps > 0 else 0.0
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{start_sec:.6f}",
            "-i", str(src),
            "-c", "copy",
            str(dest),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode("utf-8", errors="replace").strip()
            return False, err or f"ffmpeg split failed for {src.name}"
        except OSError as e:
            return False, str(e)

        if not dest.is_file() or dest.stat().st_size <= 0:
            return False, "Split produced an empty file"

        # Part A: clamp out/work to at_frame
        self.set_video_range(idx, out_frame=at_frame, work_frame=min(self.work_frame_for(idx), at_frame))

        insert_at = idx + 1
        src_idx = idx

        def _insert_dict(d, default=None, copy=True):
            out = {}
            for i, val in d.items():
                if i < insert_at:
                    out[i] = val
                else:
                    out[i + 1] = val
            if copy and src_idx in d:
                out[insert_at] = d[src_idx]
            elif default is not None:
                out[insert_at] = default
            return out

        def _insert_set(s, copy=True):
            out = set()
            for i in s:
                if i < insert_at:
                    out.add(i)
                else:
                    out.add(i + 1)
            if copy and src_idx in s:
                out.add(insert_at)
            return out

        self.image_files.insert(insert_at, dest)
        self.focal_points = _insert_dict(self.focal_points)
        self.auto_center_flags = _insert_dict(self.auto_center_flags)
        self.crop_scales = _insert_dict(self.crop_scales)
        self.flip_h = _insert_dict(self.flip_h)
        self.flip_v = _insert_dict(self.flip_v)
        self.image_dimensions = _insert_dict(self.image_dimensions)
        self.in_frames = _insert_dict(self.in_frames, copy=False)
        self.out_frames = _insert_dict(self.out_frames, copy=False)
        self.work_frames = _insert_dict(self.work_frames, copy=False)
        self.keyframes = _insert_dict(self.keyframes, copy=False)
        self.video_meta = _insert_dict(self.video_meta, copy=False)
        self.completed = _insert_set(self.completed)
        self.preview_dirty = _insert_set(self.preview_dirty)
        self.preview_dirty.add(insert_at)

        part_meta = probe_video_meta(dest)
        if part_meta:
            self.image_meta[dest.name] = part_meta
            self.image_dimensions[insert_at] = (part_meta["width"], part_meta["height"])
            self.video_meta[insert_at] = {
                "fps": float(part_meta.get("fps") or 30.0),
                "frame_count": int(part_meta.get("frame_count") or 1),
                "duration_ms": int(part_meta.get("duration_ms") or 0),
            }
            din, dout, dwork = default_video_range(part_meta["frame_count"])
            self.in_frames[insert_at] = din
            self.out_frames[insert_at] = dout
            self.work_frames[insert_at] = dwork

        for slot, names in list(self.arrangements.items()):
            if not isinstance(names, list):
                continue
            try:
                pos = names.index(src.name)
            except ValueError:
                continue
            names = list(names)
            names.insert(pos + 1, dest.name)
            self.arrangements[slot] = names

        self.save_focal_points()
        return True, None

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

                if "arrangements" in data and isinstance(data["arrangements"], dict):
                    self.arrangements = {
                        str(k): list(v) for k, v in data["arrangements"].items()
                        if isinstance(v, list)
                    }
                if "arrangement_active" in data:
                    self.arrangement_active = str(data["arrangement_active"])
                if "arrangement_reversed" in data and isinstance(data["arrangement_reversed"], dict):
                    self.arrangement_reversed = {
                        str(k): bool(v) for k, v in data["arrangement_reversed"].items()
                    }
                if "arrangement_methods" in data and isinstance(data["arrangement_methods"], dict):
                    allowed = {"color", "depth", "lead", "faces", "manual"}
                    self.arrangement_methods = {
                        str(k): str(v)
                        for k, v in data["arrangement_methods"].items()
                        if str(v) in allowed
                    }

                if "current_idx" in data:
                    self.current_idx = data["current_idx"]
                    self._current_idx_loaded = True
                
                skip_keys = {
                    "alignment_mode", "preview_state", "discarded", "current_idx",
                    "order", "_meta", "arrangements", "arrangement_active",
                    "arrangement_reversed", "arrangement_methods",
                }
                focal_data = {k: v for k, v in data.items() if k not in skip_keys}
                
                existing_files = {f.name for f in self.image_files}
                
                for filename, coords in focal_data.items():
                    if filename not in existing_files:
                        continue
                    for idx, img_file in enumerate(self.image_files):
                        if img_file.name == filename:
                            has_focal = False
                            if isinstance(coords, dict):
                                if "focal_x" in coords and "focal_y" in coords:
                                    self.focal_points[idx] = (coords.get("focal_x", 0), coords.get("focal_y", 0))
                                    has_focal = True
                                ow = coords.get("original_width", 0)
                                oh = coords.get("original_height", 0)
                                if ow and oh:
                                    self.image_dimensions[idx] = (ow, oh)
                                self.auto_center_flags[idx] = coords.get("auto_center", False)
                                if "crop_scale" in coords:
                                    self.crop_scales[idx] = clamp_crop_scale(coords.get("crop_scale"))
                                if coords.get("flip_h"):
                                    self.flip_h[idx] = True
                                if coords.get("flip_v"):
                                    self.flip_v[idx] = True
                                if "in_frame" in coords:
                                    self.in_frames[idx] = int(coords["in_frame"])
                                if "out_frame" in coords:
                                    self.out_frames[idx] = int(coords["out_frame"])
                                if "work_frame" in coords:
                                    self.work_frames[idx] = int(coords["work_frame"])
                                if "keyframes" in coords and isinstance(coords["keyframes"], list):
                                    self.keyframes[idx] = normalize_keyframes(coords["keyframes"])
                                elif has_focal and is_video_path(img_file):
                                    # Migrate legacy single focal → In/Out keyframes at work or mid.
                                    fx, fy = self.focal_points[idx]
                                    cs = clamp_crop_scale(self.crop_scales.get(idx, DEFAULT_CROP_SCALE))
                                    n = int(coords.get("frame_count") or 1)
                                    din, dout, dwork = default_video_range(n)
                                    in_f = int(coords.get("in_frame", din))
                                    out_f = int(coords.get("out_frame", dout))
                                    work = int(coords.get("work_frame", dwork))
                                    work = max(in_f, min(out_f, work))
                                    seed = [
                                        {"frame": in_f, "focal_x": fx, "focal_y": fy, "crop_scale": cs, "ease": DEFAULT_KEYFRAME_EASE},
                                        {"frame": out_f, "focal_x": fx, "focal_y": fy, "crop_scale": cs, "ease": DEFAULT_KEYFRAME_EASE},
                                    ]
                                    if work not in (in_f, out_f):
                                        seed.append({"frame": work, "focal_x": fx, "focal_y": fy, "crop_scale": cs, "ease": DEFAULT_KEYFRAME_EASE})
                                    self.keyframes[idx] = normalize_keyframes(seed, in_f=in_f, out_f=out_f)
                            elif isinstance(coords, list) and len(coords) >= 4:
                                self.focal_points[idx] = (coords[0], coords[1])
                                self.image_dimensions[idx] = (coords[2], coords[3])
                                self.auto_center_flags[idx] = False
                                has_focal = True
                            elif isinstance(coords, list) and len(coords) >= 2:
                                self.focal_points[idx] = (coords[0], coords[1])
                                self.auto_center_flags[idx] = False
                                has_focal = True
                            if has_focal:
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
        new_crop_scales = {}
        new_flip_h = {}
        new_flip_v = {}
        new_in = {}
        new_out = {}
        new_work = {}
        new_keyframes = {}
        new_vmeta = {}
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
            if old_idx in self.crop_scales:
                new_crop_scales[new_idx] = self.crop_scales[old_idx]
            if self.flip_h.get(old_idx):
                new_flip_h[new_idx] = True
            if self.flip_v.get(old_idx):
                new_flip_v[new_idx] = True
            if old_idx in self.in_frames:
                new_in[new_idx] = self.in_frames[old_idx]
            if old_idx in self.out_frames:
                new_out[new_idx] = self.out_frames[old_idx]
            if old_idx in self.work_frames:
                new_work[new_idx] = self.work_frames[old_idx]
            if old_idx in self.keyframes:
                new_keyframes[new_idx] = list(self.keyframes[old_idx])
            if old_idx in self.video_meta:
                new_vmeta[new_idx] = self.video_meta[old_idx]
        
        self.image_files = ordered
        self.focal_points = new_focal
        self.completed = new_completed
        self.auto_center_flags = new_auto_center
        self.image_dimensions = new_dimensions
        self.crop_scales = new_crop_scales
        self.flip_h = new_flip_h
        self.flip_v = new_flip_v
        self.in_frames = new_in
        self.out_frames = new_out
        self.work_frames = new_work
        self.keyframes = new_keyframes
        self.video_meta = new_vmeta
        logger.info(f"[ALIGNER _reorder_files_by_names] Reordered to {[f.name[:20] for f in ordered[:5]]}...")
    
    def _validate_and_discard_images(self):
        """Validate media via header/video probe; move undecodable files aside.

        Stores original (width, height) in image_dimensions without a full decode.
        """
        if not self.image_files:
            return
        
        invalid_indices = []
        
        for idx, img_file in enumerate(self.image_files):
            meta = probe_media_meta(img_file)
            if meta is None:
                logger.warning(f"[VALIDATE] Invalid media (cannot probe): {img_file.name}")
                invalid_indices.append(idx)
                self.invalid_images.add(img_file.name)
                continue
            self.image_dimensions[idx] = (meta["width"], meta["height"])
            self.image_meta[img_file.name] = meta
            if meta.get("media_kind") == "video":
                self.video_meta[idx] = {
                    "fps": float(meta.get("fps") or 30.0),
                    "frame_count": int(meta.get("frame_count") or 1),
                    "duration_ms": int(meta.get("duration_ms") or 0),
                }
        
        if not invalid_indices:
            logger.info(f"[VALIDATE] All {len(self.image_files)} media files are valid")
            return
        
        logger.info(f"[VALIDATE] Found {len(invalid_indices)} invalid files, moving to discarded/invalid/")
        
        invalid_folder = self.input_folder / "discarded" / "invalid"
        invalid_folder.mkdir(parents=True, exist_ok=True)
        
        for idx in reversed(invalid_indices):
            img_file = self.image_files[idx]
            dest = invalid_folder / img_file.name
            if img_file.exists():
                shutil.move(str(img_file), str(dest))
                logger.info(f"[VALIDATE] Moved invalid media to: {dest}")
        
        valid = []
        new_dims = {}
        new_vmeta = {}
        new_i = 0
        for i, f in enumerate(self.image_files):
            if i in invalid_indices:
                continue
            valid.append(f)
            if i in self.image_dimensions:
                new_dims[new_i] = self.image_dimensions[i]
            if i in self.video_meta:
                new_vmeta[new_i] = self.video_meta[i]
            new_i += 1
        self.image_files = valid
        self.image_dimensions = new_dims
        self.video_meta = new_vmeta
        
        logger.info(f"[VALIDATE] After validation: {len(self.image_files)} valid media remain")
    
    def save_focal_points(self):
        stale_indices = [idx for idx in self.focal_points.keys() if idx >= len(self.image_files)]
        for idx in stale_indices:
            del self.focal_points[idx]
            self.completed.discard(idx)
            if idx in self.auto_center_flags:
                del self.auto_center_flags[idx]
            if idx in self.crop_scales:
                del self.crop_scales[idx]
            self.keyframes.pop(idx, None)
            self.flip_h.pop(idx, None)
            self.flip_v.pop(idx, None)
        
        data = {"_meta": {
            "version": JSON_VERSION,
            "target_width": self.target_width,
            "target_height": self.target_height
        },
            "current_idx": self.current_idx,
        }
        
        data["order"] = [self.image_files[i].name for i in range(len(self.image_files))]
        
        for idx, img_file in enumerate(self.image_files):
            filename = img_file.name
            is_vid = is_video_path(img_file)
            focal = self.focal_points.get(idx)
            if focal is None and not is_vid:
                continue
            dims = self.image_dimensions.get(idx, (0, 0))
            entry = {
                "timestamp": datetime.now().isoformat(),
            }
            if focal is not None:
                entry.update({
                    "focal_x": focal[0],
                    "focal_y": focal[1],
                    "original_width": dims[0],
                    "original_height": dims[1],
                    "auto_center": self.auto_center_flags.get(idx, False),
                    "crop_scale": clamp_crop_scale(self.crop_scales.get(idx, DEFAULT_CROP_SCALE)),
                    "flip_h": bool(self.flip_h.get(idx, False)),
                    "flip_v": bool(self.flip_v.get(idx, False)),
                })
            elif dims[0] and dims[1]:
                entry["original_width"] = dims[0]
                entry["original_height"] = dims[1]
            if is_vid:
                n = int(self.video_meta.get(idx, {}).get("frame_count") or 1)
                din, dout, dwork = default_video_range(n)
                entry["media_kind"] = "video"
                entry["in_frame"] = int(self.in_frames.get(idx, din))
                entry["out_frame"] = int(self.out_frames.get(idx, dout))
                entry["work_frame"] = int(self.work_frames.get(idx, dwork))
                entry["fps"] = float(self.video_meta.get(idx, {}).get("fps") or 30.0)
                entry["frame_count"] = n
                kfs = self.keyframes_for(idx)
                if kfs:
                    entry["keyframes"] = kfs
            data[filename] = entry
        
        if self.alignment_mode:
            data["alignment_mode"] = self.alignment_mode
        
        if self.preview_state:
            data["preview_state"] = self.preview_state
        
        if self.discarded:
            data["discarded"] = list(self.discarded)

        if self.arrangements:
            data["arrangements"] = self.arrangements
        if self.arrangement_active:
            data["arrangement_active"] = self.arrangement_active
        if self.arrangement_reversed:
            data["arrangement_reversed"] = {
                k: bool(v) for k, v in self.arrangement_reversed.items() if v
            }
        if self.arrangement_methods:
            data["arrangement_methods"] = {
                k: str(v) for k, v in self.arrangement_methods.items() if v
            }
        
        try:
            tmp_path = self.json_path.with_suffix(".json.tmp")
            with open(tmp_path, 'w') as f:
                json.dump(data, f, indent=2)
            tmp_path.replace(self.json_path)
        except Exception as e:
            logger.warning(f"Warning: Could not save focal points: {e}")
    
    def set_target_size(self, width, height):
        """Update export/crop target size and mark all previews dirty."""
        self.target_width = max(1, int(width))
        self.target_height = max(1, int(height))
        self.preview_dirty = set(range(len(self.image_files)))
        # Drop cached preview JPEGs so next ensure regenerates at new size
        try:
            if self.preview_cache_folder and self.preview_cache_folder.exists():
                for f in self.preview_cache_folder.glob("*.jpg"):
                    try:
                        f.unlink()
                    except Exception:
                        pass
        except Exception:
            pass
        self.save_focal_points()
        return True

    def current_order_names(self):
        return [f.name for f in self.image_files]

    def _names_to_order(self, names):
        """Map filename list → display_order (new_pos → old_index)."""
        by_name = {f.name: i for i, f in enumerate(self.image_files)}
        if set(names) != set(by_name):
            # Allow partial: keep only known names, append missing at end
            ordered_idx = [by_name[n] for n in names if n in by_name]
            missing = [i for i in range(len(self.image_files)) if self.image_files[i].name not in set(names)]
            return ordered_idx + missing
        return [by_name[n] for n in names]

    def recall_arrangement(self, slot: str):
        slot = str(slot)
        if slot == "0":
            slot = "original"
        names = self.arrangements.get(slot)
        if not names:
            return False
        order = self._names_to_order(names)
        ok = self.apply_arrange_order(order, mark_draft=False)
        if ok:
            self.arrangement_active = slot
            self._arrange_draft = None
            self.save_focal_points()
        return ok

    def save_arrangement_slot(self, slot: str, names=None, method=None):
        slot = str(slot)
        if slot == "0":
            slot = "original"
        valid_numeric = {str(i) for i in range(1, ARRANGEMENT_SLOT_MAX + 1)}
        if slot != "original" and slot not in valid_numeric:
            return False
        self.arrangements[slot] = list(names if names is not None else self.current_order_names())
        self.arrangement_active = slot
        self.arrangement_reversed[slot] = False
        if method:
            self.arrangement_methods[slot] = str(method)
        elif method is None and slot != "original" and slot not in self.arrangement_methods:
            self.arrangement_methods[slot] = "manual"
        self._arrange_draft = None
        self.save_focal_points()
        return True

    def mark_arrange_draft(self):
        """Record that manual arrange edits are pending (committed on leave)."""
        self._arrange_draft = self.current_order_names()

    def reverse_arrangement_in_place(self):
        """Reverse current order and update the active slot; do not create a new preset."""
        n = len(self.image_files)
        if n < 2:
            return True
        order = list(range(n - 1, -1, -1))
        if not self.apply_arrange_order(order, mark_draft=False):
            return False
        active = self.arrangement_active or "original"
        self.arrangements[active] = self.current_order_names()
        self.arrangement_reversed[active] = not bool(self.arrangement_reversed.get(active, False))
        self._arrange_draft = None
        self.save_focal_points()
        return True

    def commit_arrange_draft_to_next_slot(self):
        """When leaving Arrange, batch manual edits into the next free 1–N slot."""
        if not self._arrange_draft:
            return None
        names = self.current_order_names()
        if names == self.arrangements.get(self.arrangement_active):
            self._arrange_draft = None
            return None
        valid_numeric = {str(i) for i in range(1, ARRANGEMENT_SLOT_MAX + 1)}
        # Prefer overwrite active numeric slot, else next free, else slot 1
        active = self.arrangement_active
        if active in valid_numeric:
            slot = active
        else:
            slot = next(
                (str(i) for i in range(1, ARRANGEMENT_SLOT_MAX + 1) if str(i) not in self.arrangements),
                "1",
            )
        self.save_arrangement_slot(slot, names, method="manual")
        return slot

    def auto_arrange(self, mode: str, options: Optional[dict] = None, progress_callback=None):
        """Run an AutoArrange mode and save into a slot. Returns (ok, slot|error)."""
        options = options or {}
        paths = list(self.image_files)
        # AutoArrange samples the trim start (in_frame), not the work playhead.
        frame_indices = [
            int(self.in_frames.get(i, 0)) if self.is_video(i) else None
            for i in range(len(paths))
        ]
        from arrange_auto import (
            sort_indices_by_color,
            sort_indices_by_depth,
            lead_match_sort,
            sort_indices_by_faces,
        )
        labels = None
        if mode == "color":
            order, labels = sort_indices_by_color(
                paths, progress=progress_callback, frame_indices=frame_indices,
            )
        elif mode == "depth":
            order = sort_indices_by_depth(
                paths,
                near_to_far=bool(options.get("near_to_far", True)),
                progress=progress_callback,
                frame_indices=frame_indices,
            )
        elif mode == "lead":
            order = lead_match_sort(
                paths,
                lead_index=int(options.get("lead_index", self.current_idx)),
                roi=options.get("roi"),
                axis=str(options.get("axis", "x")),
                progress=progress_callback,
                frame_indices=frame_indices,
            )
        elif mode == "faces":
            order = sort_indices_by_faces(
                paths, progress=progress_callback, frame_indices=frame_indices,
            )
        else:
            return False, f"Unknown mode: {mode}"
        if not self.apply_arrange_order(order, mark_draft=False):
            return False, "apply_arrange_order failed"
        slot = str(options.get("slot") or next(
            (
                str(i) for i in range(1, ARRANGEMENT_SLOT_MAX + 1)
                if str(i) not in self.arrangements
            ),
            "1",
        ))
        self.save_arrangement_slot(slot, method=mode)
        return True, {"slot": slot, "labels": labels, "method": mode}
    
    def delete_focal_points_file(self):
        """Delete the focal points JSON file."""
        if self.json_path.exists():
            try:
                self.json_path.unlink()
            except Exception as e:
                logger.warning(f"Warning: Could not delete focal points file: {e}")

    def _unique_duplicate_path(self, src: Path) -> Path:
        """Return input_folder / '{stem}__dup{n?}{suffix}' that does not exist yet."""
        stem = src.stem
        suffix = src.suffix
        candidate = self.input_folder / f"{stem}__dup{suffix}"
        n = 2
        while candidate.exists():
            candidate = self.input_folder / f"{stem}__dup{n}{suffix}"
            n += 1
        return candidate

    def duplicate_current(self):
        """Copy current image on disk and insert it after current_idx with the same settings.

        Returns (ok, error_message|None).
        """
        if not (0 <= self.current_idx < len(self.image_files)):
            return False, "No current image"
        src = self.image_files[self.current_idx]
        if not src.is_file():
            return False, f"Missing file: {src.name}"
        try:
            dest = self._unique_duplicate_path(src)
            shutil.copy2(src, dest)
        except Exception as e:
            return False, f"Could not copy image: {e}"

        insert_at = self.current_idx + 1
        src_idx = self.current_idx

        def _insert_dict(d, default=None):
            out = {}
            for idx, val in d.items():
                if idx < insert_at:
                    out[idx] = val
                else:
                    out[idx + 1] = val
            if src_idx in d:
                out[insert_at] = d[src_idx]
            elif default is not None:
                out[insert_at] = default
            return out

        def _insert_set(s):
            out = set()
            for idx in s:
                if idx < insert_at:
                    out.add(idx)
                else:
                    out.add(idx + 1)
            if src_idx in s:
                out.add(insert_at)
            return out

        self.image_files.insert(insert_at, dest)
        self.focal_points = _insert_dict(self.focal_points)
        self.auto_center_flags = _insert_dict(self.auto_center_flags)
        self.crop_scales = _insert_dict(self.crop_scales)
        self.flip_h = _insert_dict(self.flip_h)
        self.flip_v = _insert_dict(self.flip_v)
        self.image_dimensions = _insert_dict(self.image_dimensions)
        self.in_frames = _insert_dict(self.in_frames)
        self.out_frames = _insert_dict(self.out_frames)
        self.work_frames = _insert_dict(self.work_frames)
        self.keyframes = _insert_dict(self.keyframes)
        # Independent copies so editing one clip's keyframes does not mutate the other.
        if insert_at in self.keyframes and isinstance(self.keyframes[insert_at], list):
            self.keyframes[insert_at] = [dict(k) for k in self.keyframes[insert_at]]
        self.video_meta = _insert_dict(self.video_meta)
        if insert_at in self.video_meta and isinstance(self.video_meta[insert_at], dict):
            self.video_meta[insert_at] = dict(self.video_meta[insert_at])
        self.completed = _insert_set(self.completed)
        self.preview_dirty = _insert_set(self.preview_dirty)
        self.preview_dirty.add(insert_at)

        # Copy header meta under the new filename if known
        if src.name in self.image_meta:
            self.image_meta[dest.name] = dict(self.image_meta[src.name])
        else:
            meta = probe_media_meta(dest)
            if meta:
                self.image_meta[dest.name] = meta
                self.image_dimensions[insert_at] = (meta["width"], meta["height"])
                if meta.get("media_kind") == "video":
                    self.video_meta[insert_at] = {
                        "fps": float(meta.get("fps") or 30.0),
                        "frame_count": int(meta.get("frame_count") or 1),
                        "duration_ms": int(meta.get("duration_ms") or 0),
                    }

        # Insert into arrangement filename lists after the source name
        for slot, names in list(self.arrangements.items()):
            if not isinstance(names, list):
                continue
            try:
                pos = names.index(src.name)
            except ValueError:
                continue
            names = list(names)
            names.insert(pos + 1, dest.name)
            self.arrangements[slot] = names

        self.current_idx = insert_at
        self.save_focal_points()
        return True, None

    def _ensure_dims(self, idx):
        """Return (w, h) for idx, probing the file header if unknown."""
        dims = self.image_dimensions.get(idx)
        if dims and dims[0] > 0 and dims[1] > 0:
            return dims
        if 0 <= idx < len(self.image_files):
            meta = probe_media_meta(self.image_files[idx])
            if meta:
                size = (meta["width"], meta["height"])
                self.image_dimensions[idx] = size
                self.image_meta[self.image_files[idx].name] = meta
                if meta.get("media_kind") == "video":
                    self.video_meta[idx] = {
                        "fps": float(meta.get("fps") or 30.0),
                        "frame_count": int(meta.get("frame_count") or 1),
                        "duration_ms": int(meta.get("duration_ms") or 0),
                    }
                return size
        return None

    def thumb_path(self, img_file):
        stem = Path(img_file).stem
        if is_video_path(img_file):
            # Include work frame in the name so scrubbing regenerates thumbs.
            idx = None
            name = Path(img_file).name
            for i, f in enumerate(self.image_files):
                if f.name == name:
                    idx = i
                    break
            wf = self.work_frame_for(idx) if idx is not None else 0
            return self.thumb_folder / f"{stem}_v{wf}.jpg"
        return self.thumb_folder / f"{stem}.jpg"

    def preview_path(self, img_file, orientation="landscape"):
        # `_u8` suffix invalidates previews written before uint8 normalization.
        # Flip flags are part of the cache key so toggles regenerate aligned JPEGs.
        fh = fv = 0
        name = Path(img_file).name
        for i, f in enumerate(self.image_files):
            if f.name == name:
                fh = 1 if self.flip_h.get(i) else 0
                fv = 1 if self.flip_v.get(i) else 0
                break
        return self.preview_cache_folder / f"{Path(img_file).stem}_{orientation}_u8_f{fh}{fv}.jpg"

    def ensure_thumbnail(self, idx):
        """Write a ~512px JPEG thumb for idx if missing. Returns path or None."""
        if not (0 <= idx < len(self.image_files)):
            return None
        img_file = self.image_files[idx]
        path = self.thumb_path(img_file)
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        if is_video_path(img_file):
            img = self.load_media_bgr(idx)
            if img is None:
                return None
            h, w = img.shape[:2]
            scale = min(THUMB_MAX / max(w, 1), THUMB_MAX / max(h, 1), 1.0)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(path), small, [cv2.IMWRITE_JPEG_QUALITY, 75])
            return path
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
                meta = probe_media_meta(f) or {}
                if meta:
                    self.image_meta[f.name] = meta
                    w, h = meta.get("width") or w, meta.get("height") or h
                    if meta.get("media_kind") == "video":
                        self.video_meta[i] = {
                            "fps": float(meta.get("fps") or 30.0),
                            "frame_count": int(meta.get("frame_count") or 1),
                            "duration_ms": int(meta.get("duration_ms") or 0),
                        }
            kind = "video" if is_video_path(f) else "image"
            entry = {
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
                "crop_scale": clamp_crop_scale(self.crop_scales.get(i, DEFAULT_CROP_SCALE)) if focal else DEFAULT_CROP_SCALE,
                "flip_h": bool(self.flip_h.get(i, False)),
                "flip_v": bool(self.flip_v.get(i, False)),
                "media_kind": kind,
            }
            if kind == "video":
                vmeta = self.video_meta.get(i) or {}
                n = int(vmeta.get("frame_count") or meta.get("frame_count") or 1)
                din, dout, dwork = default_video_range(n)
                entry.update({
                    "fps": float(vmeta.get("fps") or meta.get("fps") or 30.0),
                    "frame_count": n,
                    "duration_ms": int(vmeta.get("duration_ms") or meta.get("duration_ms") or 0),
                    "in_frame": int(self.in_frames.get(i, din)),
                    "out_frame": int(self.out_frames.get(i, dout)),
                    "work_frame": int(self.work_frames.get(i, dwork)),
                    "keyframes": self.keyframes_for(i),
                })
            images.append(entry)
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
            "arrangements": {
                k: list(v) for k, v in (self.arrangements or {}).items()
            },
            "arrangement_active": self.arrangement_active or "original",
            "arrangement_reversed": bool(
                (self.arrangement_reversed or {}).get(self.arrangement_active or "original", False)
            ),
            "arrangement_methods": {
                k: str(v) for k, v in (self.arrangement_methods or {}).items() if v
            },
            "arrangement_slots": ["original"] + [str(i) for i in range(1, ARRANGEMENT_SLOT_MAX + 1)],
            "ffmpeg_available": ffmpeg_available(),
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
            focal[0], focal[1], w, h, tw, th, self.max_zoom,
            crop_scale=self.crop_scales.get(idx, DEFAULT_CROP_SCALE),
        )
        return {"x": x, "y": y, "w": cw, "h": ch, "orig_w": w, "orig_h": h,
                "target_w": tw, "target_h": th, "focal": [focal[0], focal[1]],
                "crop_scale": clamp_crop_scale(self.crop_scales.get(idx, DEFAULT_CROP_SCALE))}

    def export_aligned(self, output_folder, orientation="landscape", progress_callback=None):
        """Write aligned media to output_folder: images as {idx:04d}.jpg, videos as .mp4."""
        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)
        self.set_alignment_mode(orientation)
        total = len(self.image_files)
        exported = 0
        for i, img_file in enumerate(self.image_files):
            focal = self.focal_points.get(i)
            if focal is not None:
                if self.is_video(i):
                    ok, err = self.align_single_video(
                        i, img_file, focal, output_folder, orientation,
                        output_name=f"{i:04d}.mp4",
                        progress_callback=progress_callback,
                        file_index=i,
                        file_total=total,
                    )
                    if ok:
                        exported += 1
                    elif progress_callback and err:
                        self._emit_export_progress(
                            progress_callback, i + 1, total, img_file.name, error=err,
                        )
                else:
                    ok = self.align_single_image(
                        i, img_file, focal, output_folder, orientation,
                        output_name=f"{i:04d}.jpg",
                    )
                    if ok:
                        exported += 1
            if progress_callback:
                self._emit_export_progress(progress_callback, i + 1, total, img_file.name)
        return exported

    @staticmethod
    def _emit_export_progress(callback, done, total, name, error=None):
        if not callback:
            return
        try:
            callback(done, total, name, error=error)
        except TypeError:
            if error:
                callback(done, total, f"ERROR: {name}: {error}")
            else:
                callback(done, total, name)
    
    def get_current_image(self):
        """Load and return the current original image / work frame."""
        if 0 <= self.current_idx < len(self.image_files):
            img = self.load_media_bgr(self.current_idx)
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
    
    def set_focal_point(self, x, y, auto_center=False, crop_scale=None, flip_h=None, flip_v=None, keyframe_frame=None):
        """Set focal point for current image (in original image coordinates).

        For videos, also upserts a keyframe at keyframe_frame (or work_frame) and
        ensures In/Out endpoints exist on first set.
        """
        self._ensure_dims(self.current_idx)
        idx = self.current_idx
        
        self.focal_points[idx] = (float(x), float(y))
        self.auto_center_flags[idx] = auto_center
        if crop_scale is not None:
            self.crop_scales[idx] = clamp_crop_scale(crop_scale)
        elif idx not in self.crop_scales:
            self.crop_scales[idx] = DEFAULT_CROP_SCALE
        if flip_h is not None:
            if flip_h:
                self.flip_h[idx] = True
            else:
                self.flip_h.pop(idx, None)
        if flip_v is not None:
            if flip_v:
                self.flip_v[idx] = True
            else:
                self.flip_v.pop(idx, None)
        self.completed.add(idx)
        if self.is_video(idx):
            frame = self.work_frame_for(idx) if keyframe_frame is None else int(keyframe_frame)
            # Any focal edit writes/updates the keyframe at this frame.
            self.add_or_update_keyframe(
                idx, frame, float(x), float(y),
                crop_scale=self.crop_scales.get(idx, DEFAULT_CROP_SCALE),
                create=True,
            )
        
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
        """Clear focal point for current image.

        For videos, also removes all keyframes (In/Out mid markers alike).
        """
        idx = self.current_idx
        if idx in self.focal_points:
            del self.focal_points[idx]
        if idx in self.auto_center_flags:
            del self.auto_center_flags[idx]
        if idx in self.crop_scales:
            del self.crop_scales[idx]
        self.keyframes.pop(idx, None)
        if idx in self.completed:
            self.completed.remove(idx)
        with self._preview_generation_lock:
            self.preview_dirty.add(idx)
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
        """Align a single image (or video work-frame) with given focal point.
        
        Returns True if successful, False otherwise. For videos this writes a
        preview JPEG of the work frame; use align_single_video for MP4 export.
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
            if is_video_path(img_file):
                img = self.load_media_bgr(idx)
                load_method = "video"
            else:
                img, load_method = load_image_safely(img_file)
            if img is None:
                logger.warning(f"[align_single_image] Failed to load {img_file.name}, creating placeholder")
                output_folder.mkdir(parents=True, exist_ok=True)
                output_path = Path(output_folder) / output_name
                placeholder = np.full((target_h, target_w, 3), 128, dtype=np.uint8)
                cv2.imwrite(str(output_path), placeholder, [cv2.IMWRITE_JPEG_QUALITY, 50])
                return True

            fh = bool(self.flip_h.get(idx, False))
            fv = bool(self.flip_v.get(idx, False))
            h0, w0 = img.shape[:2]
            if focal is None:
                focal = (w0 / 2, h0 / 2)
            fx, fy = transform_focal_for_flips(focal[0], focal[1], w0, h0, fh, fv)
            img = apply_user_flips(img, fh, fv)
            
            h, w = img.shape[:2]
            self.image_dimensions[idx] = (w0, h0)
            
            aligned, _ = render_aligned(
                img, (fx, fy), target_w, target_h,
                max_zoom=self.max_zoom,
                crop_scale=self.crop_scales.get(idx, DEFAULT_CROP_SCALE),
            )
            
            output_folder = Path(output_folder)
            output_folder.mkdir(parents=True, exist_ok=True)
            output_path = output_folder / output_name
            cv2.imwrite(str(output_path), aligned, [cv2.IMWRITE_JPEG_QUALITY, 90])
            return True
        except Exception:
            return False

    def align_single_video(self, idx, img_file, focal, output_folder, orientation,
                           output_name=None, progress_callback=None,
                           file_index=0, file_total=1):
        """Export an aligned MP4 for frames in_frame..out_frame inclusive.

        Returns (ok, error_message|None).
        """
        if orientation == "portrait":
            target_w = self.target_height
            target_h = self.target_width
        else:
            target_w = self.target_width
            target_h = self.target_height

        if output_name is None:
            output_name = f"{idx:04d}.mp4"
        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)
        output_path = output_folder / output_name

        if not ffmpeg_available():
            msg = (
                f"ffmpeg not found on PATH — cannot export {img_file.name}. "
                "Install ffmpeg (e.g. brew install ffmpeg) and retry."
            )
            logger.warning(msg)
            return False, msg

        self._ensure_video_ranges()
        vmeta = self.video_meta.get(idx) or {}
        fps = float(vmeta.get("fps") or 30.0)
        n = max(1, int(vmeta.get("frame_count") or 1))
        in_f = int(self.in_frames.get(idx, 0))
        out_f = int(self.out_frames.get(idx, n - 1))
        in_f = max(0, min(in_f, n - 1))
        out_f = max(in_f, min(out_f, n - 1))
        frame_total = out_f - in_f + 1

        fh = bool(self.flip_h.get(idx, False))
        fv = bool(self.flip_v.get(idx, False))
        crop_scale = self.crop_scales.get(idx, DEFAULT_CROP_SCALE)

        # Even dimensions required for yuv420p
        enc_w = target_w if target_w % 2 == 0 else target_w + 1
        enc_h = target_h if target_h % 2 == 0 else target_h + 1

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{enc_w}x{enc_h}",
            "-r", f"{fps:.6f}",
            "-i", "pipe:0",
            "-an",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "veryfast",
            "-crf", "18",
            str(output_path),
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as e:
            return False, str(e)

        try:
            for fi, frame_idx in enumerate(range(in_f, out_f + 1)):
                frame = extract_video_frame(img_file, frame_idx)
                if frame is None:
                    frame = np.full((target_h, target_w, 3), 0, dtype=np.uint8)
                h0, w0 = frame.shape[:2]
                interp = self.interpolate_focal_at(idx, frame_idx)
                use_focal = (interp[0], interp[1])
                use_scale = interp[2]
                fx, fy = transform_focal_for_flips(use_focal[0], use_focal[1], w0, h0, fh, fv)
                flipped = apply_user_flips(frame, fh, fv)
                aligned, _ = render_aligned(
                    flipped, (fx, fy), target_w, target_h,
                    max_zoom=self.max_zoom,
                    crop_scale=use_scale,
                )
                if enc_w != target_w or enc_h != target_h:
                    canvas = np.zeros((enc_h, enc_w, 3), dtype=np.uint8)
                    canvas[:target_h, :target_w] = aligned
                    aligned = canvas
                try:
                    proc.stdin.write(aligned.tobytes())
                except BrokenPipeError:
                    err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", errors="replace")
                    return False, err or "ffmpeg pipe broken"
                if progress_callback:
                    FocalPointAlignerCore._emit_export_progress(
                        progress_callback,
                        file_index, file_total,
                        f"{img_file.name} [{fi + 1}/{frame_total}]",
                    )
            proc.stdin.close()
            stderr = proc.stderr.read() if proc.stderr else b""
            rc = proc.wait(timeout=600)
            if rc != 0:
                err = stderr.decode("utf-8", errors="replace").strip()
                return False, err or f"ffmpeg exited {rc}"
            if not output_path.is_file() or output_path.stat().st_size <= 0:
                return False, "ffmpeg produced an empty file"
            return True, None
        except Exception as e:
            try:
                proc.kill()
            except Exception:
                pass
            return False, str(e)
        finally:
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except Exception:
                pass
    
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
        new_crop_scales = {}
        
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

        for old_idx, scale in self.crop_scales.items():
            new_idx = old_to_new.get(old_idx, old_idx)
            new_crop_scales[new_idx] = scale

        new_flip_h = {}
        new_flip_v = {}
        for old_idx, flag in self.flip_h.items():
            if flag:
                new_flip_h[old_to_new.get(old_idx, old_idx)] = True
        for old_idx, flag in self.flip_v.items():
            if flag:
                new_flip_v[old_to_new.get(old_idx, old_idx)] = True
        
        self.focal_points = new_focal
        self.completed = new_completed
        self.auto_center_flags = new_auto_center
        self.image_dimensions = new_dimensions
        self.crop_scales = new_crop_scales
        self.flip_h = new_flip_h
        self.flip_v = new_flip_v
        
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
        
        new_auto = {}
        for idx, flag in self.auto_center_flags.items():
            if idx == i:
                new_auto[j] = flag
            elif idx == j:
                new_auto[i] = flag
            else:
                new_auto[idx] = flag
        self.auto_center_flags = new_auto

        new_scales = {}
        for idx, scale in self.crop_scales.items():
            if idx == i:
                new_scales[j] = scale
            elif idx == j:
                new_scales[i] = scale
            else:
                new_scales[idx] = scale
        self.crop_scales = new_scales

        def _swap_flag_map(d):
            out = {}
            for idx, flag in d.items():
                if not flag:
                    continue
                if idx == i:
                    out[j] = True
                elif idx == j:
                    out[i] = True
                else:
                    out[idx] = True
            return out
        self.flip_h = _swap_flag_map(self.flip_h)
        self.flip_v = _swap_flag_map(self.flip_v)
        
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
        self.crop_scales = _shift_dict(self.crop_scales)
        self.flip_h = _shift_dict(self.flip_h)
        self.flip_v = _shift_dict(self.flip_v)
        self.in_frames = _shift_dict(self.in_frames)
        self.out_frames = _shift_dict(self.out_frames)
        self.work_frames = _shift_dict(self.work_frames)
        self.keyframes = _shift_dict(self.keyframes)
        self.video_meta = _shift_dict(self.video_meta)
        self.completed = _shift_set(self.completed)
        self.preview_dirty = _shift_set(self.preview_dirty)
        
        self.image_files.pop(discarded_idx)
        
        if self.current_idx >= len(self.image_files):
            self.current_idx = max(0, len(self.image_files) - 1)
        
        self.save_focal_points()
        logger.info(f"[ALIGNER discard_current] DONE: current_idx={self.current_idx}, total_images={len(self.image_files)}")
    
    def apply_arrange_order(self, display_order, mark_draft=True):
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
        new_crop_scales = {}
        new_flip_h = {}
        new_flip_v = {}
        new_in = {}
        new_out = {}
        new_work = {}
        new_keyframes = {}
        new_vmeta = {}
        
        for new_pos, orig_idx in enumerate(display_order):
            if orig_idx in self.focal_points:
                new_focal[new_pos] = self.focal_points[orig_idx]
            if orig_idx in self.completed:
                new_completed.add(new_pos)
            if orig_idx in self.auto_center_flags:
                new_auto_center[new_pos] = self.auto_center_flags[orig_idx]
            if orig_idx in self.image_dimensions:
                new_dimensions[new_pos] = self.image_dimensions[orig_idx]
            if orig_idx in self.crop_scales:
                new_crop_scales[new_pos] = self.crop_scales[orig_idx]
            if self.flip_h.get(orig_idx):
                new_flip_h[new_pos] = True
            if self.flip_v.get(orig_idx):
                new_flip_v[new_pos] = True
            if orig_idx in self.in_frames:
                new_in[new_pos] = self.in_frames[orig_idx]
            if orig_idx in self.out_frames:
                new_out[new_pos] = self.out_frames[orig_idx]
            if orig_idx in self.work_frames:
                new_work[new_pos] = self.work_frames[orig_idx]
            if orig_idx in self.keyframes:
                new_keyframes[new_pos] = list(self.keyframes[orig_idx])
            if orig_idx in self.video_meta:
                new_vmeta[new_pos] = self.video_meta[orig_idx]
        
        old_order = [i for i in range(len(self.image_files))]
        if display_order != old_order:
            old_to_new = {orig_idx: new_pos for new_pos, orig_idx in enumerate(display_order)}
            self.image_files = new_files
            self.focal_points = new_focal
            self.completed = new_completed
            self.auto_center_flags = new_auto_center
            self.image_dimensions = new_dimensions
            self.crop_scales = new_crop_scales
            self.flip_h = new_flip_h
            self.flip_v = new_flip_v
            self.in_frames = new_in
            self.out_frames = new_out
            self.work_frames = new_work
            self.keyframes = new_keyframes
            self.video_meta = new_vmeta
            self.current_idx = old_to_new.get(self.current_idx, 0)
            self.preview_dirty = {
                old_to_new[idx] for idx in self.preview_dirty if idx in old_to_new
            }
            if mark_draft:
                self.mark_arrange_draft()
            
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
        self.crop_scales.clear()
        self.keyframes.clear()
        self.flip_h.clear()
        self.flip_v.clear()
        
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