import math

import numpy as np

from aligner_core import compute_crop, crop_to_widget, render_aligned


def test_crop_to_widget_mapping():
    # orig 4000x3000 shown in 800x600 widget at img origin (10, 5)
    wx, wy, ww, wh = crop_to_widget(0, 0, 2000, 1500, 10, 5, 800, 600, 4000, 3000)
    assert (wx, wy, ww, wh) == (10, 5, 400, 300)


def _make_img(w, h):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 2] = 255  # red, easy to assert on
    return img


def test_render_aligned_tiny_still_fills_frame():
    img = _make_img(500, 300)
    aligned, used_blur = render_aligned(img, (250, 150), 2560, 1440)
    assert aligned.shape[:2] == (1440, 2560)
    assert used_blur is False


def test_render_aligned_tiny_output_dims():
    img = _make_img(320, 240)
    aligned, used_blur = render_aligned(img, (160, 120), 2560, 1440)
    assert used_blur is False
    assert aligned.shape[:2] == (1440, 2560)


def test_render_aligned_large_uses_normal_path():
    img = _make_img(12000, 8000)
    aligned, used_blur = render_aligned(img, (6000, 4000), 2560, 1440)
    assert aligned.shape[:2] == (1440, 2560)
    assert used_blur is False


def test_render_aligned_medium_output_dims():
    img = _make_img(4000, 3000)
    aligned, used_blur = render_aligned(img, (1000, 1500), 2560, 1440)
    assert aligned.shape[:2] == (1440, 2560)
    assert used_blur is False


def test_render_aligned_none_focal_defaults_to_center():
    img = _make_img(4000, 3000)
    aligned, _ = render_aligned(img, None, 2560, 1440)
    assert aligned.shape[:2] == (1440, 2560)


def _run(fx, fy, ow, oh, tw=2560, th=1440):
    return compute_crop(fx, fy, ow, oh, tw, th)


def test_large_image_takes_target_sized_crop():
    x, y, w, h = _run(6000, 4000, 12000, 8000)
    assert abs(w - 2560) <= 1
    assert abs(h - 1440) <= 1
    assert abs((x + w / 2) - 6000) < 2
    assert abs((y + h / 2) - 4000) < 2


def test_medium_image_takes_target_sized_crop():
    x, y, w, h = _run(2000, 1500, 4000, 3000)
    assert abs(w - 2560) <= 1
    assert abs(h - 1440) <= 1
    assert 0 <= x <= 4000 - w
    assert 0 <= y <= 3000 - h


def test_small_image_covers_frame_and_scales_up():
    x, y, w, h = _run(250, 150, 500, 300)
    assert w == 500
    assert abs(h - 500 * 1440 / 2560) <= 2
    assert x == 0


def test_focal_is_centered_when_it_fits():
    x, y, w, h = _run(4000, 3000, 8000, 6000)
    assert abs((x + w / 2) - 4000) < 2
    assert abs((y + h / 2) - 3000) < 2


def test_focal_near_edge_clamps_crop():
    x, y, w, h = _run(10, 10, 8000, 6000)
    assert x == 0
    assert y == 0
    assert abs(w - 2560) <= 1
    assert abs(h - 1440) <= 1


def test_crop_region_aspect_matches_target():
    for ow, oh in [(12000, 8000), (4000, 3000), (500, 300)]:
        _, _, w, h = _run(ow / 2, oh / 2, ow, oh)
        cap = abs(w * 1440 - h * 2560)
        assert cap <= 2560 * 2, f"aspect off by {cap}px-cross for {ow}x{oh}"
        assert 0 <= w <= ow and 0 <= h <= oh


def test_render_aligned_puts_focal_at_center():
    """A marked pixel at the focal should land on the output center when it fits."""
    img = np.zeros((4000, 6000, 3), dtype=np.uint8)
    fx, fy = 3000, 2200
    img[fy, fx] = (0, 255, 0)
    aligned, _ = render_aligned(img, (fx, fy), 2560, 1440)
    cy, cx = 1440 // 2, 2560 // 2
    patch = aligned[cy - 3:cy + 4, cx - 3:cx + 4, 1]
    assert patch.max() == 255
    for fx, fy in [(1, 1), (2, 2), (11999, 7999)]:
        x, y, w, h = _run(fx, fy, 12000, 8000)
        assert all(math.isfinite(v) for v in (x, y, w, h))
        assert x >= 0 and y >= 0 and x + w <= 12000 and y + h <= 8000


def test_render_aligned_puts_focal_at_center():
    """A marked pixel at the focal should land on the output center when it fits."""
    img = np.zeros((4000, 6000, 3), dtype=np.uint8)
    fx, fy = 3000, 2200
    img[fy, fx] = (0, 255, 0)
    aligned, _ = render_aligned(img, (fx, fy), 2560, 1440)
    cy, cx = 1440 // 2, 2560 // 2
    patch = aligned[cy - 3:cy + 4, cx - 3:cx + 4, 1]
    assert patch.max() == 255
