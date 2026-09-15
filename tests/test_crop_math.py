import math

import numpy as np

from aligner_core import compute_crop, compute_crop_frame, crop_to_widget, render_aligned


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


def test_small_image_off_center_focal_scales_to_keep_focal_centered():
    """Off-center focal on a small source must zoom in so output centers it."""
    fx, fy = 400, 150
    x, y, w, h = _run(fx, fy, 500, 300)
    assert w < 500  # zoomed in vs full-width cover
    assert abs((x + w / 2) - fx) < 2
    assert abs((y + h / 2) - fy) < 2
    assert abs(w * 1440 - h * 2560) <= 2560 * 2


def test_focal_is_centered_when_it_fits():
    x, y, w, h = _run(4000, 3000, 8000, 6000)
    assert abs((x + w / 2) - 4000) < 2
    assert abs((y + h / 2) - 3000) < 2


def test_focal_near_edge_zooms_to_keep_focal_centered():
    fx, fy = 10, 10
    x, y, w, h = _run(fx, fy, 8000, 6000)
    assert abs((x + w / 2) - fx) < 2
    assert abs((y + h / 2) - fy) < 2
    assert w < 2560  # zoomed in vs default 1:1 target crop
    assert h < 1440


def test_crop_region_aspect_matches_target():
    for ow, oh in [(12000, 8000), (4000, 3000), (500, 300)]:
        _, _, w, h = _run(ow / 2, oh / 2, ow, oh)
        cap = abs(w * 1440 - h * 2560)
        assert cap <= 2560 * 2, f"aspect off by {cap}px-cross for {ow}x{oh}"
        assert 0 <= w <= ow and 0 <= h <= oh


def test_crop_scale_larger_includes_more():
    x0, y0, w0, h0 = compute_crop(6000, 4000, 12000, 8000, 2560, 1440, crop_scale=1.0)
    x1, y1, w1, h1 = compute_crop(6000, 4000, 12000, 8000, 2560, 1440, crop_scale=2.0)
    assert w1 > w0 and h1 > h0
    assert abs((x1 + w1 / 2) - 6000) < 2
    assert abs((y1 + h1 / 2) - 4000) < 2


def test_crop_scale_smaller_zooms_in():
    _, _, w0, h0 = compute_crop(6000, 4000, 12000, 8000, 2560, 1440, crop_scale=1.0)
    _, _, w1, h1 = compute_crop(6000, 4000, 12000, 8000, 2560, 1440, crop_scale=0.5)
    assert w1 < w0 and h1 < h0
    assert abs(w1 * 1440 - h1 * 2560) <= 2560 * 2


def test_crop_scale_clamps_to_image():
    _, _, w, h = compute_crop(250, 150, 500, 300, 2560, 1440, crop_scale=8.0)
    assert w == 500
    assert h <= 300


def test_crop_scale_out_keeps_focal_centered_near_edge():
    """Zooming out must not slide the effective crop; focal stays locked at center."""
    fx, fy = 100, 4000
    x, y, w, h = compute_crop(fx, fy, 12000, 8000, 2560, 1440, crop_scale=4.0)
    assert abs((x + w / 2) - fx) < 2
    assert abs((y + h / 2) - fy) < 2
    # Max centered width is 2 * min(fx, ow-fx) = 200
    assert w <= 200 + 2


def test_crop_frame_grows_past_edges_while_centered():
    """Requested overlay frame follows crop_scale even when it leaves the image."""
    fx, fy = 100, 4000
    f0 = compute_crop_frame(fx, fy, 12000, 8000, 2560, 1440, crop_scale=1.0)
    f1 = compute_crop_frame(fx, fy, 12000, 8000, 2560, 1440, crop_scale=2.0)
    assert f1[2] > f0[2] and f1[3] > f0[3]
    assert abs((f0[0] + f0[2] / 2) - fx) < 2
    assert abs((f1[0] + f1[2] / 2) - fx) < 2
    # Requested zoom-out extends past the left edge; effective sample stays inside.
    assert f1[0] < 0
    ex, ey, ew, eh = compute_crop(fx, fy, 12000, 8000, 2560, 1440, crop_scale=2.0)
    assert ex >= 0 and ey >= 0 and ex + ew <= 12000 and ey + eh <= 8000
    assert abs((ex + ew / 2) - fx) < 2
    assert ew < f1[2]


def test_render_aligned_upscales_when_edge_limits_zoom_out():
    """Near-edge + large crop_scale still fills the frame with a centered crop."""
    img = _make_img(12000, 8000)
    fx, fy = 80, 4000
    x, y, w, h = compute_crop(fx, fy, 12000, 8000, 2560, 1440, crop_scale=4.0)
    assert abs((x + w / 2) - fx) < 2
    assert abs((y + h / 2) - fy) < 2
    assert w < 2560  # must upscale to fill target
    aligned, used_blur = render_aligned(img, (fx, fy), 2560, 1440, crop_scale=4.0)
    assert used_blur is False
    assert aligned.shape[:2] == (1440, 2560)


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
