"""AutoArrange helpers: color, depth (ONNX CPU), ORB lead-match, faces (YuNet)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
MODEL_CACHE = ROOT / ".fpa_models"
DEPTH_MODEL_NAME = "depth_anything_v2_vits_uint8.onnx"
# Public Depth-Anything-V2 small ONNX (uint8) — not gated.
DEPTH_MODEL_URLS = (
    "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model_uint8.onnx",
    "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model_quantized.onnx",
)
FACE_MODEL_NAME = "face_detection_yunet_2023mar.onnx"
FACE_MODEL_URLS = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
)

_HTTP_HEADERS = {"User-Agent": "FocalPointAligner/1.0"}

# Hue buckets: (name, hue_center_deg in OpenCV 0-179 scale half-degrees... use 0-180)
COLOR_BUCKETS = [
    ("red", 0),
    ("orange", 15),
    ("yellow", 30),
    ("green", 60),
    ("cyan", 90),
    ("blue", 120),
    ("purple", 150),
]


VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm'}


def _load_bgr(path, max_side=256, frame_idx=None):
    path = Path(path)
    img = None
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        # Lazy import avoids circular import at module load (core imports us).
        from aligner_core import extract_video_frame
        idx = 0 if frame_idx is None else int(frame_idx)
        img = extract_video_frame(path, idx)
    else:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    return img


def _frame_for(frame_indices, i):
    if not frame_indices:
        return None
    if i < 0 or i >= len(frame_indices):
        return None
    return frame_indices[i]


def classify_dominant_color(path, frame_idx=None) -> tuple[str, float]:
    """Return (label, sort_key) — whites/grays/blacks first by lightness, else hue bucket."""
    img = _load_bgr(path, 192, frame_idx=frame_idx)
    if img is None:
        return ("unknown", 999.0)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    # Sample pixels
    s_f = s.astype(np.float32).ravel()
    v_f = v.astype(np.float32).ravel()
    h_f = h.astype(np.float32).ravel()
    # Near-white: high V, low S
    white_mask = (v_f >= 200) & (s_f <= 40)
    black_mask = v_f <= 40
    gray_mask = (s_f <= 35) & (~white_mask) & (~black_mask)
    white_frac = float(white_mask.mean())
    black_frac = float(black_mask.mean())
    gray_frac = float(gray_mask.mean())
    if white_frac >= 0.35:
        return ("mostly white", 0.0 + (1.0 - float(v_f[white_mask].mean() / 255.0 if white_mask.any() else 0)))
    if black_frac >= 0.35:
        return ("mostly black", 100.0 + float(v_f.mean() / 255.0))
    if gray_frac >= 0.45:
        return ("mostly gray", 50.0 + float(v_f.mean() / 255.0))
    # Chromatic: dominant hue among saturated pixels
    chroma = s_f >= 50
    if not chroma.any():
        return ("mostly gray", 50.0 + float(v_f.mean() / 255.0))
    hues = h_f[chroma]
    # Histogram over 180 bins
    hist, _ = np.histogram(hues, bins=180, range=(0, 180))
    peak = int(hist.argmax())
    best_name = "red"
    best_dist = 999
    for name, center in COLOR_BUCKETS:
        # circular distance on 0-180
        d = min(abs(peak - center), 180 - abs(peak - center))
        if d < best_dist:
            best_dist = d
            best_name = name
    lightness = float(v_f.mean() / 255.0)
    # Sort by hue bucket order then lightness
    order = {n: i for i, (n, _) in enumerate(COLOR_BUCKETS)}
    return (best_name, 200.0 + order.get(best_name, 0) * 10 + lightness)


def sort_indices_by_color(paths: list[Path], progress=None, frame_indices=None) -> tuple[list[int], list[str]]:
    scored = []
    labels = []
    total = len(paths)
    for i, p in enumerate(paths):
        label, key = classify_dominant_color(p, frame_idx=_frame_for(frame_indices, i))
        scored.append((key, i))
        labels.append(label)
        if progress:
            progress(i + 1, total, Path(p).name)
    scored.sort(key=lambda t: t[0])
    return [i for _, i in scored], labels


def _download_to(dest: Path, urls: tuple[str, ...], *, min_bytes: int = 100_000) -> Path:
    """Download first working URL into dest via temp file (atomic rename)."""
    import httpx

    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in urls:
        tmp_fd, tmp_name = tempfile.mkstemp(suffix=".onnx", dir=MODEL_CACHE)
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)
        try:
            with httpx.stream(
                "GET",
                url,
                headers=_HTTP_HEADERS,
                follow_redirects=True,
                timeout=120.0,
            ) as resp:
                resp.raise_for_status()
                with open(tmp_path, "wb") as out:
                    for chunk in resp.iter_bytes():
                        out.write(chunk)
            if tmp_path.stat().st_size < min_bytes:
                raise RuntimeError(f"downloaded file too small ({tmp_path.stat().st_size} bytes)")
            tmp_path.replace(dest)
            return dest
        except Exception as e:
            errors.append(f"{url}: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
    raise RuntimeError("; ".join(errors) if errors else "no download URLs")


def _existing_onnx(exclude_names: Optional[set[str]] = None, min_bytes: int = 100_000) -> Optional[Path]:
    exclude_names = exclude_names or set()
    if not MODEL_CACHE.is_dir():
        return None
    for alt in sorted(MODEL_CACHE.glob("*.onnx"), key=lambda p: p.stat().st_size, reverse=True):
        if alt.name in exclude_names:
            continue
        if alt.stat().st_size >= min_bytes:
            return alt
    return None


def _ensure_depth_model() -> Path:
    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    dest = MODEL_CACHE / DEPTH_MODEL_NAME
    if dest.exists() and dest.stat().st_size > 100_000:
        return dest
    # Prefer any user-placed depth-like ONNX (exclude YuNet face model)
    alt = _existing_onnx(exclude_names={FACE_MODEL_NAME}, min_bytes=1_000_000)
    if alt is not None:
        return alt
    try:
        return _download_to(dest, DEPTH_MODEL_URLS, min_bytes=100_000)
    except Exception as e:
        raise RuntimeError(
            f"Could not download depth model to {dest}: {e}. "
            "Place a Depth-Anything or MiDaS ONNX file in .fpa_models/ or pip install onnxruntime."
        ) from e


def _depth_session():
    try:
        import onnxruntime as ort
    except ImportError as e:
        raise RuntimeError(
            "Depth sort requires onnxruntime. Install with: pip install onnxruntime"
        ) from e
    model = _ensure_depth_model()
    opts = ort.SessionOptions()
    opts.inter_op_num_threads = 2
    opts.intra_op_num_threads = 2
    return ort.InferenceSession(str(model), sess_options=opts, providers=["CPUExecutionProvider"])


def mean_center_depth(path, session=None, frame_idx=None) -> float:
    """Higher = farther (typical inverse-depth models vary; we use mean of center crop)."""
    img = _load_bgr(path, 384, frame_idx=frame_idx)
    if img is None:
        return 0.0
    sess = session or _depth_session()
    # Generic preprocess: RGB float NCHW 1x3xH×W, ImageNet-ish
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    # Many DA-V2 ONNX expect 518×518; resize
    size = 518
    resized = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_CUBIC)
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    norm = (resized - mean) / std
    inp = norm.transpose(2, 0, 1)[None, ...].astype(np.float32)
    input_name = sess.get_inputs()[0].name
    out = sess.run(None, {input_name: inp})[0]
    depth = np.squeeze(out).astype(np.float32)
    if depth.ndim != 2:
        depth = depth.reshape(depth.shape[-2], depth.shape[-1])
    ch, cw = depth.shape
    y0, x0 = ch // 4, cw // 4
    y1, x1 = ch - y0, cw - x0
    center = depth[y0:y1, x0:x1]
    return float(center.mean())


def sort_indices_by_depth(paths: list[Path], near_to_far: bool = True, progress=None,
                          frame_indices=None) -> list[int]:
    total = len(paths)
    if progress:
        progress(0, total, "loading depth model…")
    session = _depth_session()
    scored = []
    for i, p in enumerate(paths):
        try:
            d = mean_center_depth(p, session=session, frame_idx=_frame_for(frame_indices, i))
        except Exception:
            d = 0.0
        scored.append((d, i))
        if progress:
            progress(i + 1, total, Path(p).name)
    scored.sort(key=lambda t: t[0], reverse=not near_to_far)
    return [i for _, i in scored]


def _orb_descriptors(img_bgr, roi=None):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    if roi is not None:
        x, y, w, h = [int(v) for v in roi]
        x = max(0, x)
        y = max(0, y)
        gray = gray[y:y + h, x:x + w]
        offset = (x, y)
    else:
        offset = (0, 0)
    orb = cv2.ORB_create(nfeatures=800)
    kps, desc = orb.detectAndCompute(gray, None)
    if not kps or desc is None:
        return [], None, offset
    # Shift keypoints back to full-image coords
    for kp in kps:
        kp.pt = (kp.pt[0] + offset[0], kp.pt[1] + offset[1])
    return kps, desc, offset


def lead_match_sort(
    paths: list[Path],
    lead_index: int = 0,
    roi=None,
    axis: str = "x",
    progress=None,
    frame_indices=None,
) -> list[int]:
    """Sort by matched feature centroid along axis relative to lead image ROI/features."""
    total = len(paths)
    if progress:
        progress(0, total, "scanning lead…")
    lead_img = _load_bgr(paths[lead_index], 640, frame_idx=_frame_for(frame_indices, lead_index))
    if lead_img is None:
        return list(range(len(paths)))
    # Scale ROI if provided in original coords — assume already in loaded image space if small
    lead_kps, lead_desc, _ = _orb_descriptors(lead_img, roi=roi)
    if lead_desc is None:
        return list(range(len(paths)))
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    scored = []
    for i, p in enumerate(paths):
        img = _load_bgr(p, 640, frame_idx=_frame_for(frame_indices, i))
        if img is None:
            scored.append((1e9, i))
            if progress:
                progress(i + 1, total, Path(p).name)
            continue
        kps, desc, _ = _orb_descriptors(img)
        if desc is None or len(kps) < 4:
            scored.append((1e9, i))
            if progress:
                progress(i + 1, total, Path(p).name)
            continue
        matches = bf.knnMatch(lead_desc, desc, k=2)
        good = []
        for pair in matches:
            if len(pair) < 2:
                continue
            m, n = pair
            if m.distance < 0.75 * n.distance:
                good.append(m)
        if len(good) < 4:
            scored.append((1e9, i))
            if progress:
                progress(i + 1, total, Path(p).name)
            continue
        pts = np.array([kps[m.trainIdx].pt for m in good], dtype=np.float32)
        cx, cy = float(pts[:, 0].mean()), float(pts[:, 1].mean())
        key = cx if axis == "x" else cy
        scored.append((key, i))
        if progress:
            progress(i + 1, total, Path(p).name)
    scored.sort(key=lambda t: t[0])
    return [i for _, i in scored]


def _ensure_face_model() -> Path:
    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    dest = MODEL_CACHE / FACE_MODEL_NAME
    if dest.exists() and dest.stat().st_size > 50_000:
        return dest
    try:
        return _download_to(dest, FACE_MODEL_URLS, min_bytes=50_000)
    except Exception as e:
        raise RuntimeError(
            f"Could not download face model to {dest}: {e}. "
            f"Place {FACE_MODEL_NAME} (YuNet) in .fpa_models/."
        ) from e


def _face_detector(input_size=(320, 320)):
    if not hasattr(cv2, "FaceDetectorYN_create"):
        raise RuntimeError(
            "Faces sort requires OpenCV FaceDetectorYN (opencv-python >= 4.5.4)."
        )
    model = _ensure_face_model()
    return cv2.FaceDetectorYN_create(str(model), "", input_size, 0.6, 0.3, 5000)


def face_centroid_x(path, detector=None, frame_idx=None) -> Optional[float]:
    """Return normalized face center x in [0,1] using OpenCV YuNet (FaceDetectorYN)."""
    img = _load_bgr(path, 640, frame_idx=frame_idx)
    if img is None:
        return None
    h, w = img.shape[:2]
    try:
        det = detector or _face_detector((w, h))
        det.setInputSize((w, h))
        _retval, faces = det.detect(img)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Face detection failed: {e}") from e
    if faces is None or len(faces) == 0:
        return None
    # Each row: x, y, w, h, … — take largest by area
    best = max(faces, key=lambda f: float(f[2]) * float(f[3]))
    x, y, fw, fh = float(best[0]), float(best[1]), float(best[2]), float(best[3])
    return (x + fw / 2) / max(1.0, float(w))


def sort_indices_by_faces(paths: list[Path], progress=None, frame_indices=None) -> list[int]:
    total = len(paths)
    if progress:
        progress(0, total, "loading face model…")
    detector = _face_detector((320, 320))
    scored = []
    for i, p in enumerate(paths):
        try:
            cx = face_centroid_x(p, detector=detector, frame_idx=_frame_for(frame_indices, i))
        except RuntimeError:
            raise
        except Exception:
            cx = None
        scored.append((1e9 if cx is None else cx, i))
        if progress:
            progress(i + 1, total, Path(p).name)
    scored.sort(key=lambda t: t[0])
    return [i for _, i in scored]
