# Image Size Handling — Design Spec

Date: 2026-08-12
Status: Approved

## Problem

Aligned output (target, by default 2560×1440 for landscape) is computed by
`aligner_core.calculate_transformation`, which chooses the zoom scale as
`max(orig_w/target_w, orig_h/target_h)`. Two failure modes:

1. **Much-too-large images** — the selected scale grows with the source size, so
   a 12000×8000 photo is cropped to show only ~3.8% of its width (feels "too
   zoomed in", a useless crop). It also materializes a ~9 GB intermediate buffer
   (resize-then-crop) that risks OOM.
2. **Much-too-small images** — the same math upscales a 500×300 photo ~5.1× to
   fill the target, producing heavy pixelation.

Users want: large images framed so the whole (or a sensible amount of the) image
is visible; small images not blown up into mush; and live feedback about exactly
what will be kept vs cropped, controlled by an adjustable zoom setting.

## Approach (approved)

Restructure the crop math around a **bounded zoom** model: the full-frame fit is the
baseline, and a user-facing **zoom slider** caps how far in toward the focal point
the crop may go. Undersized images fall back to a **blurred-backdrop fill** (sharp
subject at ≤2× upscale over a blurred/darkened stretched copy of the same image).
Rewriting the transform to **crop-then-resize** eliminates the giant intermediate
buffer.

Default constants (must be easy to tweak, see docs):

- `DEFAULT_MAX_ZOOM = 3.0` — slider default (range **1×–6×**).
- `UPSCALE_CAP = 2.0` — max upscale of the sharp subject before the blur-fill
  path engages.
- Slider range **1.0–6.0**, step 0.5.

## Changes

### 1. Core crop math — `aligner_core.py`

Replace `calculate_transformation` with two pure functions (legacy copies in
`align_focal_points.py` and `scripts/align_and_scale_images.py` are left
untouched):

- `compute_crop(focal_x, focal_y, orig_w, orig_h, target_w, target_h,
  max_zoom=DEFAULT_MAX_ZOOM) -> tuple[int, int, int, int]`
  Returns `(x, y, w, h)` — the crop rectangle **in original-pixel space**:
  - `cover = max(target_w/orig_w, target_h/orig_h)` — scale that fits the *whole
    image* to the frame (for large images this is a downscale < 1).
  - `focal_scale = max(target_w/(2*focal_x), target_w/(2*(orig_w-focal_x)),
    target_h/(2*focal_y), target_h/(2*(orig_h-focal_y)))` — scale needed to
    center the focal point (guarded against division by zero).
  - `scale = min(max(cover, focal_scale), cover * max_zoom)`.
  - Crop region width `w = target_w / scale`, height `h = target_h / scale`,
    anchored so the focal point maps to the region center; clamped to image
    bounds.
  - Focal floats clamped into `[1, orig-1]` as before.
- `render_aligned(img, focal, target_w, target_h, max_zoom=DEFAULT_MAX_ZOOM)
  -> np.ndarray` — a single entry point used by both export and preview:
  - `scale = cover'ish` decision: compute the transform, and if the required
    scale (`max(cover, focal_scale)`) **exceeds** `UPSCALE_CAP × cover`'s
    upscaling... precisely: if `cover > 1` (source smaller than target) **and**
    the sharp subject would need more than `UPSCALE_CAP` upscale, use the
    **blur-fill** path:
    - Sharp region rendered at up to `UPSCALE_CAP` scale, centered on the focal.
    - Backdrop = full source `cv2.resize`d to target + heavy `GaussianBlur` +
      darkening, with the sharp region composited on top.
  - Otherwise (normal/smallish path): `cv2.resize` **only the crop region** to
    the target dims (crop-then-resize). Output is always exactly
    `(target_h, target_w)`.
  - Returns `(aligned, used_blur_fill_bool)` so callers/tests can assert which
    path ran.

`align_single_image` (export) calls `render_aligned` instead of the inline
resize-then-crop block. Placeholder/failed-load behavior and orientation
swapping are unchanged.

### 2. Preview — `ui/preview_worker.py`

- Call `render_aligned` (drop the duplicated inline math).
- Fix a latent inconsistency: previews currently hardcode 2560×1440 instead of
  `core.target_width/height`; use the core's configured target dims and the
  current `max_zoom` so preview reliably matches export and overlay.

### 3. Crop-region overlay — `ui/image_display.py`

- New `set_crop_policy(target_w, target_h, orientation, max_zoom)`; store on the
  widget. `orientation` selects `(target_w,target_h)` vs swapped portrait dims.
- In `paintEvent` (which already draws the focal crosshair): compute the crop
  rect via `compute_crop` on the original-image dims, map it to display coords
  using `_displayed_pixmap_rect` + `scale_x/scale_y`, dim the *excluded* area
  with a semi-transparent dark fill (~55% black), and draw a bright rect outline;
  keep the focal crosshair on top.
- Pure `crop_to_widget(crop_rect, pixmap_rect, orig_w, orig_h,
  disp_w, disp_h) -> tuple` helper for unit-testable rect mapping.
- When no crop policy is set (e.g. preview tab reusing the widget), no overlay
  is drawn — behavior unchanged.

### 4. Zoom slider — `ui/aligner_screen.py` + persistence

- `QSlider` (range 1.0–6.0, step 0.5, default 3.0) + value `QLabel`, placed in
  the Original-tab header row (near the ↻ orientation button).
- On change: `core.max_zoom = value`; repaint the overlay widget; mark all
  previews dirty (`core.preview_dirty = set(range(...))`) so Preview and export
  regenerate with the new crop.
- Persist `max_zoom` in `config.json` via `ui/opener_screen.py` (alongside its
  existing prefs). Both single and batch config flows (batch built in
  `main.py:_open_next_batch_folder`) read it.

### 5. Tests — `tests/test_crop_math.py` (new; pure Python, no Qt import)

- `compute_crop`:
  - Large 12000×8000 at default zoom shows ≥ ~25% of the width (vs 3.8% today);
    at zoom 1× shows the full image (Option A behavior).
  - 4000×3000 centered shows the full image; off-center focal in `[cover,
    cover×max_zoom]` bounds.
  - Out-of-bounds focal clamps; no zero/inf division.
  - Crop region always `(w,h)` in target aspect, within image bounds.
- `render_aligned`:
  - Tiny 500×300 / 320×240 → output exactly target dims; `used_blur_fill=True`;
    sharp region not upscaled > 2×.
  - Large/medium → `used_blur_fill=False` and output target dims.
- `crop_to_widget` mapping helper math.

### 6. Docs

- README: a **"Sensible framing & image sizes"** section documenting
  `DEFAULT_MAX_ZOOM`, `UPSCALE_CAP`, slider range, and behavior for large/small
  images — explicitly framed as constants that may be tweaked in the future.
- AGENTS.md: note `compute_crop`/`render_aligned`, `test_crop_math.py`, and the
  zoom slider + constants (same numbers, easy to tweak).

## Out of scope

- Legacy `align_focal_points.py`, `scripts/align_and_scale_images.py`,
  `align_and_scale_images.py` copies.
- Upscaling quality beyond the blur-fill approach (user confirmed no super-res).
- Auto-auto_center or focal-detection changes.