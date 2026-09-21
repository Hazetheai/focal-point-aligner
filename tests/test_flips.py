"""Flip H/V persistence and render_aligned orientation."""
from pathlib import Path

import cv2
import numpy as np

from aligner_core import (
    FocalPointAlignerCore,
    apply_user_flips,
    transform_focal_for_flips,
    render_aligned,
)


def _write_gradient(path: Path, w=200, h=100):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    for x in range(w):
        img[:, x] = (x % 256, 40, 200 - (x % 200))
    # Distinct left/right markers
    img[:, 0:10] = (0, 0, 255)  # red strip left (BGR)
    img[:, -10:] = (0, 255, 0)  # green strip right
    cv2.imwrite(str(path), img)


def test_transform_and_apply_flips():
    fx, fy = transform_focal_for_flips(10, 20, 100, 50, flip_h=True, flip_v=False)
    assert abs(fx - 89) < 1e-6
    assert abs(fy - 20) < 1e-6
    img = np.zeros((20, 40, 3), dtype=np.uint8)
    img[:, 0] = 255
    flipped = apply_user_flips(img, flip_h=True, flip_v=False)
    assert flipped[0, -1, 0] == 255


def test_flip_roundtrip_json_and_export(tmp_path):
    src = tmp_path / "imgs"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    _write_gradient(src / "a.jpg")

    core = FocalPointAlignerCore({
        "input_folder": str(src),
        "output_folder": str(out),
        "target_width": 80,
        "target_height": 40,
    })
    core.set_focal_point(20, 50, crop_scale=1.0, flip_h=True, flip_v=False)
    core.save_focal_points()
    snap = core.session_snapshot()
    assert snap["images"][0]["flip_h"] is True
    assert snap["images"][0]["flip_v"] is False

    data = (src / "focal_points.json").read_text()
    assert '"flip_h": true' in data

    core2 = FocalPointAlignerCore({
        "input_folder": str(src),
        "output_folder": str(out),
        "target_width": 80,
        "target_height": 40,
    })
    assert core2.flip_h.get(0) is True
    assert not core2.flip_v.get(0)

    ok = core2.align_single_image(
        0, core2.image_files[0], core2.focal_points[0], out, "landscape",
        output_name="0000.jpg",
    )
    assert ok
    aligned = cv2.imread(str(out / "0000.jpg"))
    assert aligned is not None
    assert aligned.shape[0] == 40 and aligned.shape[1] == 80


def test_render_aligned_with_flipped_bitmap():
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    img[:, 0:20] = (0, 0, 255)
    img[:, 180:200] = (0, 255, 0)
    flipped = apply_user_flips(img, flip_h=True)
    fx, fy = transform_focal_for_flips(10, 50, 200, 100, flip_h=True)
    out, _ = render_aligned(flipped, (fx, fy), 80, 40, crop_scale=1.0)
    assert out.shape[0] == 40 and out.shape[1] == 80
