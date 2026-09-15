"""Core I/O: header-only dims, filename-keyed cache, confirm does not write full-res."""

from pathlib import Path

import cv2
import numpy as np

from aligner_core import FocalPointAlignerCore, probe_image_meta, probe_image_size


def _make_images(img_dir, count=4, size=(1920, 1080)):
    img_dir.mkdir(parents=True, exist_ok=True)
    w, h = size
    for i in range(count):
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:, :] = (i * 40, 80, 160)
        cv2.imwrite(str(img_dir / f"image{i:04d}.jpg"), img)


def _make_core(tmp_path, count=4):
    img_dir = tmp_path / "test_images"
    _make_images(img_dir, count)
    return FocalPointAlignerCore({
        "input_folder": str(img_dir),
        "output_folder": str(tmp_path / "output"),
        "target_width": 640,
        "target_height": 360,
    })


def test_probe_image_size_reads_headers(tmp_path):
    img_dir = tmp_path / "imgs"
    _make_images(img_dir, 1, size=(800, 600))
    assert probe_image_size(img_dir / "image0000.jpg") == (800, 600)


def test_probe_image_meta_includes_dpi_and_pixels(tmp_path):
    from PIL import Image as PILImage

    path = tmp_path / "dpi.jpg"
    im = PILImage.new("RGB", (640, 480), (10, 20, 30))
    im.save(path, format="JPEG", dpi=(300, 300), quality=90)
    meta = probe_image_meta(path)
    assert meta["width"] == 640
    assert meta["height"] == 480
    assert meta["bytes"] > 0
    assert meta["dpi"] is not None
    assert abs(meta["dpi"][0] - 300) < 1
    assert meta["format"] in ("jpeg", "jpg")


def test_exif_orientation_matches_displayed_size(tmp_path):
    from PIL import Image as PILImage

    from aligner_core import load_image_safely

    path = tmp_path / "rotated.jpg"
    im = PILImage.new("RGB", (40, 20), (0, 255, 0))
    im.putpixel((0, 0), (255, 0, 0))
    exif = im.getexif()
    exif[0x0112] = 6  # 90° CW
    im.save(path, exif=exif)
    assert probe_image_size(path) == (20, 40)
    img, _ = load_image_safely(path)
    assert img.shape[1] == 20 and img.shape[0] == 40


def test_init_stores_dimensions_without_preview_folders(tmp_path):
    core = _make_core(tmp_path)
    assert core.image_dimensions[0] == (1920, 1080)
    assert not (tmp_path / "test_images_preview_landscape").exists()
    assert (tmp_path / "test_images").exists()


def test_confirm_and_save_does_not_write_full_res_output(tmp_path):
    core = _make_core(tmp_path)
    core.set_focal_point(100, 80)
    idx_before = core.current_idx
    assert core.confirm_and_save() is True
    # No {idx:04d}.jpg dumped into the output folder as a side effect of save.
    leftovers = list((tmp_path / "output").glob("*.jpg"))
    assert leftovers == [], leftovers
    assert core.current_idx == idx_before + 1


def test_ensure_preview_does_not_persist_unset_focal(tmp_path):
    core = _make_core(tmp_path)
    assert 0 not in core.focal_points
    assert core.ensure_preview_for_current("landscape") is True
    assert 0 not in core.focal_points
    assert not core.auto_center_flags.get(0)
    assert core.preview_path(core.image_files[0], "landscape").exists()


def test_thumb_and_preview_keyed_by_filename(tmp_path):
    core = _make_core(tmp_path)
    core.focal_points[0] = (960.0, 540.0)
    thumb = core.ensure_thumbnail(0)
    assert thumb is not None and thumb.exists()
    assert thumb.name == "image0000.jpg"
    assert ".fpa_cache" in str(thumb)

    assert core.ensure_preview_for_current("landscape") is True
    preview = core.preview_path(core.image_files[0], "landscape")
    assert preview.exists()
    assert preview.name == "image0000_landscape.jpg"


def test_reorder_does_not_wipe_filename_previews(tmp_path):
    core = _make_core(tmp_path)
    core.focal_points[0] = (960.0, 540.0)
    core.ensure_preview_for_current("landscape")
    preview = core.preview_path(core.image_files[0], "landscape")
    assert preview.exists()

    assert core.apply_arrange_order([1, 0, 2, 3]) is True
    # Same file still has its preview; cache was not wiped.
    moved = next(f for f in core.image_files if f.name == "image0000.jpg")
    assert core.preview_path(moved, "landscape").exists()


def test_discard_preserves_remaining_order(tmp_path):
    core = _make_core(tmp_path)
    assert core.apply_arrange_order([3, 2, 1, 0]) is True
    core.current_idx = 1  # image0002 after arrange
    core.discard_current()
    names = [f.name for f in core.image_files]
    assert names == ["image0003.jpg", "image0001.jpg", "image0000.jpg"]
