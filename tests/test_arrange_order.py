"""Regression tests for arrange-order bugs:

1. Discarded images must not remain in the Arrange grid / display order.
2. The arranged order must propagate to image_files (=> export) and survive reload.
"""

import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_DIR))

from aligner_core import FocalPointAlignerCore


def _make_images(img_dir, count=5):
    import cv2
    import numpy as np

    img_dir.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        img[:, :] = (i * 40, i * 40, i * 40)
        cv2.imwrite(str(img_dir / f"image{i:04d}.jpg"), img)


def _make_core(tmp_path, count=5, **kwargs):
    img_dir = tmp_path / "test_images"
    _make_images(img_dir, count)
    output_dir = tmp_path / "output"
    config = {
        "input_folder": str(img_dir),
        "output_folder": str(output_dir),
        **kwargs,
    }
    return FocalPointAlignerCore(config)


def _set_all_focal(core, count=None):
    count = count or len(core.image_files)
    for i in range(count):
        core.focal_points[i] = (960.0, 540.0)
        core.completed.add(i)
        core.auto_center_flags[i] = True
        core.image_dimensions[i] = (1920, 1080)


def test_apply_arrange_order_after_discard():
    """Apply a valid-length arrange order after a discard: files and focal points follow."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        core = _make_core(Path(tmp_dir), count=5)
        _set_all_focal(core)

        core.current_idx = 2
        core.discard_current()
        assert len(core.image_files) == 4, "expected 4 images after one discard"
        # After discarding image0002 the remaining files are still in sorted order:
        assert [f.name for f in core.image_files] == [
            "image0000.jpg", "image0001.jpg", "image0003.jpg", "image0004.jpg"
        ]

        display_order = [2, 0, 1, 3]  # length == image_files length post-discard
        assert core.apply_arrange_order(display_order) is True

        names = [f.name for f in core.image_files]
        assert names == ["image0003.jpg", "image0000.jpg", "image0001.jpg", "image0004.jpg"], names

        # Focal points must have followed the files to their new index positions.
        for new_pos in range(4):
            assert new_pos in core.focal_points, f"focal point missing at {new_pos}"


def test_discard_breaks_stale_display_order_apply():
    """A stale (pre-discard length) display order must NOT silently become 'no change'."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        core = _make_core(Path(tmp_dir), count=5)
        _set_all_focal(core)

        stale_order = list(range(5))
        core.current_idx = 2
        core.discard_current()

        # Stale order length (5) no longer matches image_files (4): should fail loudly.
        assert core.apply_arrange_order(stale_order) is False


def test_order_persists_through_reload():
    """Arranged order must be restored after re-instantiating the core."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        core = _make_core(tmp_path, count=5)
        _set_all_focal(core)

        assert core.apply_arrange_order([2, 0, 1, 3, 4]) is True
        core.save_focal_points()

        reloaded = _make_core(tmp_path, count=5)
        names = [f.name for f in reloaded.image_files]
        assert names == ["image0002.jpg", "image0000.jpg", "image0001.jpg", "image0003.jpg", "image0004.jpg"], names


def test_apply_arrange_order_keeps_current_image():
    """current_idx must follow the selected file, not the old slot."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        core = _make_core(Path(tmp_dir), count=5)
        _set_all_focal(core)
        core.current_idx = 0
        name = core.image_files[0].name
        assert core.apply_arrange_order([1, 2, 0, 3, 4]) is True
        assert core.image_files[core.current_idx].name == name
        assert core.current_idx == 2
