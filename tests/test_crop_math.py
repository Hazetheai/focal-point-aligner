import math

from aligner_core import (
    compute_crop,
    DEFAULT_MAX_ZOOM,
    UPSCALE_CAP,
)


def _run(fx, fy, ow, oh, tw, th, max_zoom=DEFAULT_MAX_ZOOM):
    x, y, w, h = compute_crop(fx, fy, ow, oh, tw, th, max_zoom)
    return x, y, w, h


def test_large_image_uses_reasonable_fraction():
    x, y, w, h = _run(6000, 4000, 12000, 8000, 2560, 1440)
    frac = w / 12000
    assert frac >= 0.25, f"too zoomed: only {frac*100:.1f}% of width"


def test_large_image_at_zoom_one_is_full_image():
    x, y, w, h = _run(6000, 4000, 12000, 8000, 2560, 1440, max_zoom=1.0)
    assert w >= 12000 * 0.999, f"expected full image, got region width {w}"


def test_medium_centered_focal_shows_full_width():
    # 4:3 into 16:9 at center: cover fills the frame, whole width visible,
    # excess height cropped (cover semantics, the approved baseline)
    x, y, w, h = _run(2000, 1500, 4000, 3000, 2560, 1440)
    assert w >= 4000 * 0.999
    assert y >= 0 and y + h <= 3000


def test_medium_offcenter_zoom_is_bounded():
    _, _, w, h = _run(1000, 1500, 4000, 3000, 2560, 1440)
    cover = max(2560 / 4000, 1440 / 3000)
    scale = 2560 / w
    assert scale >= cover * 0.999
    assert scale <= cover * DEFAULT_MAX_ZOOM * 1.001


def test_crop_region_aspect_matches_target():
    # dims are integer-rounded, so allow ~2px on the cross-product
    for ow, oh in [(12000, 8000), (4000, 3000), (500, 300)]:
        _, _, w, h = _run(ow / 2, oh / 2, ow, oh, 2560, 1440)
        cap = abs(w * 1440 - h * 2560)
        assert cap <= 2560 * 2, f"aspect off by {cap}px-cross for {ow}x{oh}"
        assert 0 <= w <= ow and 0 <= h <= oh


def test_out_of_bounds_focal_clamps():
    # focal near/at corners must not blow up or produce inf/nan
    for fx, fy in [(1, 1), (2, 2), (11999, 7999)]:
        x, y, w, h = _run(fx, fy, 12000, 8000, 2560, 1440)
        assert all(math.isfinite(v) for v in (x, y, w, h))
        assert x >= 0 and y >= 0 and x + w <= 12000 and y + h <= 8000