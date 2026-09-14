export const DEFAULT_MAX_ZOOM = 3.0

/** Port of aligner_core.compute_crop — 1:1 target crop, or cover-upscale if smaller. */
export function computeCrop(focalX, focalY, origW, origH, targetW, targetH) {
  const cover = origW && origH ? Math.max(targetW / origW, targetH / origH) : 1
  const scale = Math.max(cover, 1)
  const w = Math.min(origW, Math.max(1, targetW / scale))
  const h = Math.min(origH, Math.max(1, targetH / scale))
  const fx = Math.max(0, Math.min(focalX, origW))
  const fy = Math.max(0, Math.min(focalY, origH))
  let x = fx - w / 2
  let y = fy - h / 2
  x = Math.min(Math.max(x, 0), origW - w)
  y = Math.min(Math.max(y, 0), origH - h)
  return {
    x: Math.round(x),
    y: Math.round(y),
    w: Math.round(w),
    h: Math.round(h),
  }
}
