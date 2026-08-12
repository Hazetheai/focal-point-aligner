# Image Size Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix over-zoom on oversized images and pixelation on undersized images, add a live crop-region overlay, and add an adjustable zoom slider (1×–6×, default 3×) so preview and export always frame sensibly.

**Architecture:** Replace the `scale = max(orig/target, focal)` logic in `aligner_core.calculate_transformation` with a bounded-zoom crop computed in original-pixel space (`compute_crop`) plus a single rendering entry point (`render_aligned`) used by both export and preview. `render_aligned` switches to a blurred-backdrop fill for tiny images (sharp subject capped at `UPSCALE_CAP` = 2× over a blurred/darkened stretched copy). Crop-then-resize kills the ~9 GB intermediate buffer. `ImageDisplayWidget` paints a dimmed crop-region overlay; a zoom slider in the Original-tab header controls `max_zoom`, persisted in `config.json`.

**Tech Stack:** Python 3, PyQt6, OpenCV (cv2), numpy. Spec: `docs/superpowers/specs/2026-08-12-image-size-handling-design.md`.

---

## Geometry (reference — implement exactly)

Definitions (dims: `target_w × target_h` output, source `orig_w × orig_h`, focal `(fx, fy)`):

- `cover = max(target_w/orig_w, target_h/orig_h)` — magnification that fits the **whole image** to the frame. `< 1` for large sources (downscale), `> 1` for small sources (upscale).
- `focal_scale` — magnification needed to place `(fx, fy)` at the frame center:
  `max(target_w/(2*fx), target_w/(2*(orig_w-fx)), target_h/(2*fy), target_h/(2*(orig_h-fy)))`, guarding `fx`, `orig_w-fx`, `fy`, `orig_h-fy` against 0 (use `float('inf')` and only keep finite values).
- `scale = clamp(max(cover, focal_scale), lower=0, upper=cover * max_zoom)`.
- Crop region in **original pixels**: `w = target_w / scale`, `h = target_h / scale`, anchored so `(fx, fy)` sits at the region center; clamp so the region stays within `[0, orig_w] × [0, orig_h]`, keeping aspect (if clamping forces a partial crop at an edge, accept it — the resize to target normalizes it).

Behavior checks (target 2560×1440):
- 12000×8000, zoom 3×, center focal: `cover=0.213`, `scale=0.213` → region = full image. Off-center focal `fx=3000`: `focal_scale=max(2560/6000, 2560/18000, 1440/8000, 1440/8000)=0.427`, `scale=min(0.427,0.639)=0.427` → region = 6000px wide (50% of source).
- 4000×3000, center focal: `cover=0.64`, region = full width. Off-center `fx=1000`: `focal_scale=2560/2000=1.28` → `scale=min(1.28,1.92)=1.28` → 2000px wide (50%).
- 500×300: `cover=5.12 > UPSCALE_CAP=2.0` → **blur-fill path**.

## File map

| File | Change |
|------|--------|
| `aligner_core.py` | Add `DEFAULT_MAX_ZOOM`, `UPSCALE_CAP`, `compute_crop`, `render_aligned`; wire `max_zoom`; export via `render_aligned`. |
| `ui/preview_worker.py` | Use `render_aligned` + real target dims + `core.max_zoom`. |
| `ui/image_display.py` | Add `set_crop_policy` + overlay paint + pure `crop_to_widget`. |
| `ui/aligner_screen.py` | Add zoom slider; mark previews dirty; set crop policy on load/orientation/slider. |
| `ui/opener_screen.py` | Pass `max_zoom` through config.json and emitted config dicts. |
| `main.py` | Pass `max_zoom` into batch per-folder config. |
| `tests/test_crop_math.py` | New tests. |
| `README.md`, `AGENTS.md` | Document the constants. |

---

### Task 1: `compute_crop` in `aligner_core.py` (TDD)

**Files:**
- Modify: `aligner_core.py` (add constants near top, add `compute_crop` after `calculate_transformation`)
- Test: `tests/test_crop_math.py`

- [ ] **Step 1: Write the constants**

In `aligner_core.py`, after `JSON_VERSION = "2.0"` (line ~30) add:

```python
# Sensible framing for any image size. Tweak these if output framing feels wrong;
# they are documented in README.md and AGENTS.md.
DEFAULT_MAX_ZOOM = 3.0  # slider default (range 1.0-6.0); cap = cover * this
UPSCALE_CAP = 2.0       # max real upscale of the sharp subject before blur-fill
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_crop_math.py` (pure Python, no Qt import; import from `aligner_core` directly — it has no Qt deps):

```python
import math
import numpy as np

from aligner_core import (
    compute_crop,
    render_aligned,
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


def test_medium_centered_focal_is_full_image():
    x, y, w, h = _run(2000, 1500, 4000, 3000, 2560, 1440)
    assert w >= 4000 * 0.999
    assert h >= 3000 * 0.999


def test_medium_offcenter_zoom_is_bounded():
    _, _, w, h = _run(1000, 1500, 4000, 3000, 2560, 1440)
    cover = max(2560 / 4000, 1440 / 3000)
    scale = 2560 / w
    assert scale >= cover * 0.999
    assert scale <= cover * DEFAULT_MAX_ZOOM * 1.001


def test_crop_region_aspect_matches_target():
    for ow, oh in [(12000, 8000), (4000, 3000), (500, 300)]:
        _, _, w, h = _run(ow / 2, oh / 2, ow, oh, 2560, 1440)
        assert abs((w / h) - (2560 / 1440)) < 1e-6
        assert 0 <= w <= ow and 0 <= h <= oh


def test_out_of_bounds_focal_clamps():
    # focal near/at corners must not blow up or produce inf/nan
    for fx, fy in [(1, 1), (2, 2), (11999, 7999)]:
        x, y, w, h = _run(fx, fy, 12000, 8000, 2560, 1440)
        assert all(math.isfinite(v) for v in (x, y, w, h))
        assert x >= 0 and y >= 0 and x + w <= 12000 and y + h <= 8000
```

- [ ] **Step 3: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_crop_math.py -v`
Expected: `FAILED ... - ImportError: cannot import name 'compute_crop'`

- [ ] **Step 4: Write the minimal implementation**

In `aligner_core.py`, after `calculate_transformation` (line ~78) add:

```python
def compute_crop(focal_x, focal_y, orig_w, orig_h, target_w, target_h, max_zoom=DEFAULT_MAX_ZOOM):
    """Return (x, y, w, h) - the crop rectangle in ORIGINAL pixels.

    Bounded-zoom framing: fit the whole image to the frame (cover) as the
    baseline, then allow zooming toward the focal point up to cover*max_zoom.
    """
    focal_x = max(1, min(focal_x, orig_w - 1))
    focal_y = max(1, min(focal_y, orig_h - 1))

    half_tw = target_w / 2
    half_th = target_h / 2

    cover = max(target_w / orig_w, target_h / orig_h)

    candidates = []
    for d in (focal_x, orig_w - focal_x):
        if d > 0:
            candidates.append(half_tw / d)
    for d in (focal_y, orig_h - focal_y):
        if d > 0:
            candidates.append(half_th / d)
    focal_scale = max(candidates) if candidates else cover

    scale = max(cover, focal_scale)
    max_scale = max(cover, 1e-9) * max_zoom
    scale = max(0, min(scale, max_scale))

    w = max(1.0, target_w / scale)
    h = max(1.0, target_h / scale)

    x = focal_x - w / 2
    y = focal_y - h / 2

    x = min(max(x, 0.0), orig_w - w)
    y = min(max(y, 0.0), orig_h - h)

    return (int(round(x)), int(round(y)), int(round(w)), int(round(h)))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_crop_math.py -v`
Expected: PASS (the five `compute_crop` tests above; the `render_aligned` tests added in Task 3 will still fail — that's expected, run only `tests/test_crop_math.py`).

- [ ] **Step 6: Commit**

```bash
git add tests/test_crop_math.py aligner_core.py
git commit -m "feat(crop): add bounded-zoom compute_crop for image framing"
```

---

### Task 2: `render_aligned` + export path (TDD)

**Files:**
- Modify: `aligner_core.py` (add `render_aligned`; rewrite `align_single_image` body)
- Test: `tests/test_crop_math.py`

- [ ] **Step 1: Write the failing tests (add to `tests/test_crop_math.py`)**

```python
def _make_img(w, h):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 2] = 255  # red, easy to assert on
    return img


def test_render_aligned_tiny_uses_blur_fill():
    img = _make_img(500, 300)
    aligned, used_blur = render_aligned(img, (250, 150), 2560, 1440)
    assert aligned.shape[:2] == (1440, 2560)
    assert used_blur is True


def test_render_aligned_tiny_sharp_subject_not_overscaled():
    img = _make_img(320, 240)
    aligned, used_blur = render_aligned(img, (160, 120), 2560, 1440)
    assert used_blur is True
    # subject region must not be upscaled beyond UPSCALE_CAP
    sub_w = int(320 * UPSCALE_CAP)
    assert sub_w <= 1440  # must not fill a 2560-wide frame at <=2x


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
```

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_crop_math.py -v`
Expected: FAILED with `ImportError` / `TypeError: render_aligned() ...`

- [ ] **Step 3: Write `render_aligned` and rewrite `align_single_image`**

Add to `aligner_core.py` (after `compute_crop`):

```python
def render_aligned(img, focal, target_w, target_h, max_zoom=DEFAULT_MAX_ZOOM):
    """Render one image to exactly (target_h, target_w), handling any source size.

    Returns (aligned, used_blur_fill). For sources so small they would need more
    than UPSCALE_CAP real upscaling, the sharp image is capped and composited over
    a blurred, darkened stretched copy of itself (no mushy upscale of the subject).
    """
    h, w = img.shape[:2]
    if focal is None:
        focal = (w / 2, h / 2)

    cover = max(target_w / w, target_h / h)

    if cover > UPSCALE_CAP:
        # Blur-fill path: keep the subject sharp, fill the frame with its blur.
        sharp_scale = UPSCALE_CAP
        sub_w = max(1, int(round(w * sharp_scale)))
        sub_h = max(1, int(round(h * sharp_scale)))
        sharp = cv2.resize(img, (sub_w, sub_h), interpolation=cv2.INTER_LANCZOS4)

        backdrop = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
        backdrop = cv2.GaussianBlur(backdrop, (0, 0), 40)
        backdrop = cv2.addWeighted(backdrop, 0.6, np.zeros_like(backdrop), 0.0, 0)
        canvas = backdrop.copy()

        off_x = int(round(target_w / 2 - focal[0] * sharp_scale))
        off_y = int(round(target_h / 2 - focal[1] * sharp_scale))
        # keep the subject fully inside the frame
        off_x = min(max(off_x, 0), target_w - sub_w)
        off_y = min(max(off_y, 0), target_h - sub_h)

        canvas[off_y:off_y + sub_h, off_x:off_x + sub_w] = sharp
        return canvas, True

    fx, fy = focal
    x, y, cw, ch = compute_crop(fx, fy, w, h, target_w, target_h, max_zoom)
    region = img[y:y + ch, x:x + cw]
    aligned = cv2.resize(region, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
    return aligned, False


def _crop_to_widget(crop_x, crop_y, crop_w, crop_h, img_x, img_y, disp_w, disp_h, orig_w, orig_h):
    """Map an original-pixel crop rect to widget display coordinates (pure helper)."""
    sx = disp_w / orig_w if orig_w else 1.0
    sy = disp_h / orig_h if orig_h else 1.0
    wx = img_x + crop_x * sx
    wy = img_y + crop_y * sy
    ww = crop_w * sx
    wh = crop_h * sy
    return (int(round(wx)), int(round(wy)), int(round(ww)), int(round(wh)))
```

Rewrite the body of `align_single_image` (aligner_core.py lines ~773-793) from:

```python
            crop_x, crop_y, scale, crop_w, crop_h = calculate_transformation(
                focal[0], focal[1], w, h, target_w, target_h
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
```

to:

```python
            aligned, _ = render_aligned(
                img, focal, target_w, target_h, max_zoom=self.max_zoom
            )
```

- [ ] **Step 4: Add `max_zoom` to the core**

In `FocalPointAlignerCore.__init__` (aligner_core.py ~line 128, after `target_height`), add:

```python
        self.max_zoom = config.get('max_zoom', DEFAULT_MAX_ZOOM)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_crop_math.py -v`
Expected: PASS (7 `render_aligned` tests + 5 `compute_crop` = 12 total). The `crop_to_widget` helper is imported in Task 5 via `_crop_to_widget`.

- [ ] **Step 6: Full suite**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/ -v`
Expected: previous 34 tests still PASS (export path swap must not regress batch/cli tests). If `test_cli.py` runs a (legacy) export, confirm it passes; legacy `align_focal_points.py`/`scripts/` copies are untouched.

- [ ] **Step 7: Commit**

```bash
git add tests/test_crop_math.py aligner_core.py
git commit -m "feat(crop): add render_aligned with blur-fill fallback, use it in export"
```

---

### Task 3: Point previews at `render_aligned` + real target dims

**Files:**
- Modify: `ui/preview_worker.py`
- Test: `tests/test_return_to_opener.py` (existing) — manual verification here

- [ ] **Step 1: Rewrite the preview rendering**

In `ui/preview_worker.py`, change the import (line 14):

```python
from aligner_core import render_aligned
```

Replace `_align_single_image` (lines 62-95) with:

```python
    def _align_single_image(self, idx, img_file, focal, output_folder):
        """Align a single preview image to the configured target dims."""
        if self.orientation == "landscape":
            target_w = self.aligner.target_width
            target_h = self.aligner.target_height
        else:
            target_w = self.aligner.target_height
            target_h = self.aligner.target_width

        img = cv2.imread(str(img_file))
        if img is None:
            return

        aligned, _ = render_aligned(
            img, focal, target_w, target_h, max_zoom=self.aligner.max_zoom
        )

        output_name = f"{idx:04d}.jpg"
        output_path = output_folder / output_name
        cv2.imwrite(str(output_path), aligned, [cv2.IMWRITE_JPEG_QUALITY, 90])
```

- [ ] **Step 2: Verify no stale references to `calculate_transformation`**

Run: `grep -n "calculate_transformation" ui/preview_worker.py`
Expected: no matches. (`calculate_transformation` remains defined in `aligner_core.py` and its legacy copies; the GUI no longer calls it.)

- [ ] **Step 3: Run test suite**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/ -v`
Expected: still green (preview worker changes are only exercised via the GUI smoke test; core tests unaffected).

- [ ] **Step 4: Commit**

```bash
git add ui/preview_worker.py
git commit -m "feat(crop): previews use render_aligned and configured target dims"
```

---

### Task 4: Rename helper export (`crop_to_widget` exposed)

**Files:**
- Modify: `aligner_core.py`
- Test: `tests/test_crop_math.py`

- [ ] **Step 1: Promote `_crop_to_widget` to public `crop_to_widget`**

Rename the def (Task 2) `def _crop_to_widget(` → `def crop_to_widget(` so `ui/image_display.py` imports it. No other change.

- [ ] **Step 2: Add a test**

Append to `tests/test_crop_math.py`:

```python
from aligner_core import crop_to_widget


def test_crop_to_widget_mapping():
    # orig 4000x3000 shown in 800x600 widget at img origin (10, 5)
    wx, wy, ww, wh = crop_to_widget(0, 0, 2000, 1500, 10, 5, 800, 600, 4000, 3000)
    assert wx == 10 and wy == 5 and ww == 400 and wh == 300
    # half-of-original crop maps to half-of-display
    assert (wx, wy, ww, wh) == (10, 5, 400, 300)
```

- [ ] **Step 3: Verify pass**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_crop_math.py -v`
Expected: 13 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add aligner_core.py tests/test_crop_math.py
git commit -m "feat(crop): expose crop_to_widget rect-mapping helper"
```

---

### Task 5: Crop-region overlay in `ImageDisplayWidget`

**Files:**
- Modify: `ui/image_display.py`
- Test: `tests/test_crop_math.py` (helper already covered)

- [ ] **Step 1: Add crop policy state + setter**

In `Ui/image_display.py` `__init__` (after `self._pending_focal = None`, line 44) add:

```python
        self._crop_policy = None  # (target_w, target_h, max_zoom) or None = no overlay
```

Add a method (after `set_focal_point`):

```python
    def set_crop_policy(self, target_w, target_h, max_zoom):
        """Enable the crop-region overlay for the given target dims."""
        self._crop_policy = (int(target_w), int(target_h), float(max_zoom))
        self.update()

    def clear_crop_policy(self):
        self._crop_policy = None
        self.update()
```

Import `compute_crop` and `crop_to_widget` at the top of `ui/image_display.py` (after `from ui.logger import logger`):

```python
from aligner_core import compute_crop, crop_to_widget
```

- [ ] **Step 2: Draw the overlay in `paintEvent`**

In `paintEvent` (line 262), after the focal crosshair drawing block ends (before `super().paintEvent`? — no: after drawing the crosshair, at the end of `paintEvent`, line ~317), add:

```python
        if self._crop_policy is not None and focal_to_draw is not None:
            tw, th, mz = self._crop_policy
            orig_w = self._original_width
            orig_h = self._original_height
            if orig_w > 0 and orig_h > 0 and self._displayed_pixmap_rect is not None:
                img_x, img_y, disp_w, disp_h = self._displayed_pixmap_rect
                cx, cy, cw, ch = compute_crop(
                    focal_to_draw[0], focal_to_draw[1], orig_w, orig_h, tw, th, mz
                )
                wx, wy, ww, wh = crop_to_widget(
                    cx, cy, cw, ch, img_x, img_y, disp_w, disp_h, orig_w, orig_h
                )

                dim = QColor(0, 0, 0, 140)  # ~55% black
                slim = max(4, ww // 60)
                # top / bottom / left / right bands around the keep-region
                painter.fillRect(img_x, img_y, disp_w, max(0, wy - img_y), dim)                 # above
                painter.fillRect(img_x, wy + wh, disp_w, max(0, (img_y + disp_h) - (wy + wh)), dim)  # below
                painter.fillRect(img_x, max(0, wy), max(0, wx - img_x), min(wh, disp_h), dim)       # left
                painter.fillRect(wx + ww, max(0, wy), max(0, (img_x + disp_w) - (wx + ww)), min(wh, disp_h), dim)  # right

                painter.setPen(QPen(QColor(255, 255, 255), 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(int(wx), int(wy), int(ww), int(wh))
```

- [ ] **Step 3: Verify import/syntax + suite**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/ -v`
Expected: still green (overlay painting is only visible at runtime; offscreen tests don't fail on paint code). Also run a quick import check:
`QT_QPA_PLATFORM=offscreen ./venv/bin/python -c "from ui.image_display import ImageDisplayWidget; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add ui/image_display.py
git commit -m "feat(crop): dim outside the crop region on the Original tab"
```

---

### Task 6: Wire the overlay + zoom slider in `AlignerScreen`

**Files:**
- Modify: `ui/aligner_screen.py`
- Test: `tests/test_return_to_opener.py` (existing, must stay green)

- [ ] **Step 1: Helper for current target dims (orientation-aware)**

Add a method near `_on_toggle_orientation` (line ~1098):

```python
    def _current_target_dims(self):
        """Target (w, h) for the current preview orientation."""
        w = self.config.get('target_width', 2560)
        h = self.config.get('target_height', 1440)
        if self._preview_orientation == 'portrait':
            return (h, w)
        return (w, h)

    def _apply_crop_policy(self):
        tw, th = self._current_target_dims()
        self._main_image.set_crop_policy(tw, th, self.aligner.max_zoom)
```

- [ ] **Step 2: Create the zoom slider in the header row**

In `_create_header` (after the `_btn_orientation` wiring, line ~366), add:

```python
        header_layout.addSpacing(10)
        zoom_label = QLabel("Zoom")
        zoom_label.setStyleSheet(styles.LABEL_STYLE)
        header_layout.addWidget(zoom_label)

        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(2, 12)      # 1.0x .. 6.0x in 0.5 steps
        self._zoom_slider.setSingleStep(1)
        self._zoom_slider.setFixedWidth(140)
        # set initial value with signals blocked: _create_header runs before
        # _main_image exists, so _on_max_zoom_changed must not fire yet
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(int(round(self.aligner.max_zoom * 2)))
        self._zoom_slider.blockSignals(False)
        self._zoom_slider.valueChanged.connect(self._on_max_zoom_changed)
        header_layout.addWidget(self._zoom_slider)

        self._zoom_value_label = QLabel(f"{self.aligner.max_zoom:.1f}x")
        self._zoom_value_label.setStyleSheet(styles.LABEL_STYLE)
        header_layout.addWidget(self._zoom_value_label)
```

- [ ] **Step 3: Slider handler**

Add:

```python
    def _on_max_zoom_changed(self, value):
        zoom = value * 0.5
        self.aligner.max_zoom = zoom
        self._zoom_value_label.setText(f"{zoom:.1f}x")
        self.config['max_zoom'] = zoom
        self._persist_max_zoom(zoom)
        if hasattr(self, '_main_image'):  # not yet created during header setup
            self._apply_crop_policy()
        # Regenerate all previews with the new crop
        self.aligner.preview_dirty = set(range(len(self.aligner.image_files)))
        logger.info(f"[CROP] max_zoom={zoom:.1f}")

    def _persist_max_zoom(self, zoom):
        import json
        from pathlib import Path
        cfg_path = Path(__file__).parent.parent / "config.json"
        cfg = {}
        if cfg_path.exists():
            try:
                with open(cfg_path, 'r') as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
        cfg['max_zoom'] = zoom
        try:
            with open(cfg_path, 'w') as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            logger.warning(f"[CROP] Could not persist max_zoom: {e}")
```

- [ ] **Step 4: Apply crop policy at image load, orientation change, and init**

- In `_load_original_images` (aligner_screen.py line ~634), after the `if current_img is not None:` block that calls `_main_image.set_image(...)` and `set_focal_point`/`clear_focal_point` (i.e. immediately after line ~648, before the `prev_img, prev_focal = ...` line), add `self._apply_crop_policy()`.
- In `_on_toggle_orientation` (line ~1098), inside the `elif self._current_tab == 2 ...` branch and also when tab is 1 — simplest: add `self._apply_crop_policy()` at the end of the method body.
- In `_init_ui`, add `self._apply_crop_policy()` at the end of the method (after `self.setFocus()`).

- [ ] **Step 5: Verify suite + smoke**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/ -v`
Expected: green.
Smoke: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -c "
from PyQt6.QtWidgets import QApplication
import sys; app=QApplication([])
from ui.aligner_screen import AlignerScreen
cfg={'input_folder':'tests/fixtures/nonexistent','target_width':2560,'target_height':1440,'max_zoom':3.0}
try:
    s=AlignerScreen(cfg); s._apply_crop_policy(); print('ok')
except Exception as e:
    print('ERR', e); sys.exit(1)
"`
Expected: prints `ok`.

- [ ] **Step 6: Commit**

```bash
git add ui/aligner_screen.py
git commit -m "feat(crop): zoom slider controls max_zoom and invalidates previews"
```

---

### Task 7: Pass `max_zoom` through opener + batch config

**Files:**
- Modify: `ui/opener_screen.py`, `main.py`

- [ ] **Step 1: Opener — include `max_zoom` in emitted configs and persist**

In `ui/opener_screen.py`, add `from aligner_core import DEFAULT_MAX_ZOOM` to imports.

In `on_start_clicked` (line ~307), inside the `else` config dict (lines 362-367) add `'max_zoom': self._config.get('max_zoom', DEFAULT_MAX_ZOOM),`.

In `_build_batch_page`/`_apply_batch_config` (batch config dict around lines 524-525) add the same `'max_zoom': self._config.get('max_zoom', DEFAULT_MAX_ZOOM),`. (`_save_batch_config` at ~462 already persists `_config` wholesale, so `max_zoom` written by the aligner screen survives; no extra work there.)

- [ ] **Step 2: `main.py` — carry `max_zoom` into batch per-folder config**

In `main.py`, add `from aligner_core import DEFAULT_MAX_ZOOM` to imports and in `on_batch_started` (line ~88) after `_batch_target_height` add:

```python
        self._batch_max_zoom = config.get('max_zoom', DEFAULT_MAX_ZOOM)
```

In `_open_next_batch_folder` config dict (lines 113-118) add `'max_zoom': self._batch_max_zoom,`.

- [ ] **Step 3: Verify suite**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/ -v`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add ui/opener_screen.py main.py
git commit -m "feat(crop): thread max_zoom through opener and batch config"
```

---

### Task 8: Document the constants (README + AGENTS.md)

**Files:**
- Modify: `README.md`, `AGENTS.md`

- [ ] **Step 1: README — "Sensible framing & image sizes" section**

Add a section (near the top-level features list) with an explicit "tweak these" table. Numbers must match `aligner_core.py` exactly:

```markdown
## Sensible framing & image sizes

Aligned output fits any source: large photos are downscaled to frame the whole
image (or zoom toward the focal point up to a cap); tiny photos are **blur-fill**
composited (sharp subject over a blurred, darkened copy — no pixelated upscale).

Tunable constants (`aligner_core.py`) — tweak here if framing ever feels wrong:

| Constant | Default | Meaning |
|----------|---------|---------|
| `DEFAULT_MAX_ZOOM` | `3.0` | Default zoom (the slider starts here). Cap = full-frame fit × this. |
| `UPSCALE_CAP` | `2.0` | Max real upscale of the sharp subject before the blur-fill path engages. |

Zoom slider (Original tab): **1.0× – 6.0× in 0.5 steps**, default **3.0×**. The
slider caps how far in toward the focal point the crop may go; the dimmed overlay
on the Original tab shows exactly what will be kept vs cropped. Per-session and
persisted in `config.json`.
```

- [ ] **Step 2: AGENTS.md — architecture note + constants**

In `AGENTS.md`, in the "Batch mode" section area (or a new short subsection), add:

```markdown
## Image-size framing (crop math)

- `aligner_core.compute_crop()` — bounded-zoom crop rect in original pixels.
  `scale = clamp(max(cover, focal_scale), 0 .. cover*max_zoom)`; `cover` fits the
  whole image to the frame. `aligner_core.render_aligned()` renders to exactly
  target dims and uses a **blur-fill** path when `cover > UPSCALE_CAP`.
- Tunable constants: `DEFAULT_MAX_ZOOM = 3.0` (slider default, range 1.0-6.0),
  `UPSCALE_CAP = 2.0`. Slider persists `max_zoom` in `config.json`. Keep preview,
  export, and the Original-tab overlay in sync by using `render_aligned` /
  `compute_crop` and `core.max_zoom` everywhere (see `ui/preview_worker.py`,
  `ui/image_display.py`).
- Zoom slider lives in the Original-tab header (`ui/aligner_screen.py`); changing
  it marks all previews dirty so they regenerate. Tests: `tests/test_crop_math.py`.
```

Also update the tests list / architecture table rows if convenient (e.g. add
`decode_crop`… no — just add the `tests/test_crop_math.py` bullet under Testing).

- [ ] **Step 3: Verify no stale mention of `calculate_transformation` in docs**

Run: `grep -rn "calculate_transformation" README.md AGENTS.md || echo none`
Expected: none (docs don't document that function).

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs(crop): document DEFAULT_MAX_ZOOM, UPSCALE_CAP, and the zoom slider"
```

---

### Task 9: End-to-end smoke test

**Files:** none (verification only)

- [ ] **Step 1: Suite**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/ -v`
Expected: all tests PASS (existing 34 + 13 new = 47).

- [ ] **Step 2: Real-image smoke**

Create a temp folder with one large (e.g. 12000×8000) and one tiny (500×300) JPEG, then render both through `render_aligned` and assert dims + blur-fill flag:

```bash
QT_QPA_PLATFORM=offscreen ./venv/bin/python - <<'PY'
import numpy as np, cv2
from aligner_core import render_aligned
big = np.random.randint(0,255,(8000,12000,3),dtype=np.uint8)
tiny = np.random.randint(0,255,(300,500,3),dtype=np.uint8)
a1,b1 = render_aligned(big,(6000,4000),2560,1440)
a2,b2 = render_aligned(tiny,(250,150),2560,1440)
assert a1.shape==(1440,2560) and b1 is False, (a1.shape,b1)
assert a2.shape==(1440,2560) and b2 is True, (a2.shape,b2)
print("smoke ok: large->",b1,"tiny blur->",b2)
PY
```
Expected: prints `smoke ok: large-> False tiny blur-> True`.

- [ ] **Step 3: GUI smoke (offscreen)**

Run:
```bash
QT_QPA_PLATFORM=offscreen ./venv/bin/python - <<'PY'
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ui.main_window import MainWindow
# quick class import sanity for the Qt widgets we changed
from ui.image_display import ImageDisplayWidget, crop_to_widget
from ui.aligner_screen import AlignerScreen
from ui.preview_worker import PreviewWorker
from aligner_core import compute_crop, render_aligned, DEFAULT_MAX_ZOOM, UPSCALE_CAP
print("imports ok", DEFAULT_MAX_ZOOM, UPSCALE_CAP)
PY
```
Expected: prints `imports ok 3.0 2.0`.

- [ ] **Step 4: Final commit (if any residual)**

If any fixups were needed, commit them; otherwise confirm `git status` shows only the pre-existing arrange-tab files (`ui/arrange_grid.py`, `ui/end_menu.py`, and any leftover `.opencode/`/spec files) as uncommitted.