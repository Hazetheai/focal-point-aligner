export const DEFAULT_MAX_ZOOM = 3.0
export const DEFAULT_CROP_SCALE = 1.0
export const MIN_CROP_SCALE = 0.05
export const MAX_CROP_SCALE = 8.0

export function clampCropScale(cropScale) {
  const value = Number(cropScale)
  if (!Number.isFinite(value)) return DEFAULT_CROP_SCALE
  return Math.min(MAX_CROP_SCALE, Math.max(MIN_CROP_SCALE, value))
}

function cropScales(focalX, focalY, origW, origH, targetW, targetH, cropScale) {
  const eps = 1e-6
  const fx = Math.max(eps, Math.min(focalX, origW - eps))
  const fy = Math.max(eps, Math.min(focalY, origH - eps))
  const aspect = targetH ? targetW / targetH : 1
  const maxHalfW = Math.min(fx, origW - fx)
  const maxHalfH = Math.min(fy, origH - fy)
  let hFit = 2 * Math.min(maxHalfH, maxHalfW / aspect)
  hFit = Math.max(1, Math.min(hFit, origH))
  let wFit = hFit * aspect
  if (wFit > origW) {
    wFit = origW
    hFit = wFit / aspect
  }

  const cover = Math.max(targetW / origW, targetH / origH)
  const s0 = Math.max(1, cover)
  const sFit = Math.max(targetW / wFit, targetH / hFit)
  const scaleFactor = clampCropScale(cropScale)
  let sReq = s0 / scaleFactor
  const sMax = s0 / MIN_CROP_SCALE
  sReq = Math.max(s0 / MAX_CROP_SCALE, Math.min(sReq, sMax))
  const sEff = Math.max(sReq, sFit)
  return { fx, fy, s0, sReq, sEff, wFit, hFit }
}

/**
 * If edge cover forces magnification beyond the requested crop_scale, bake that
 * into crop_scale so panning back to center keeps the same zoom.
 */
export function bakeCropScale(focalX, focalY, origW, origH, targetW, targetH, cropScale) {
  if (!origW || !origH || !targetW || !targetH) return clampCropScale(cropScale)
  const { s0, sReq, sEff } = cropScales(
    focalX, focalY, origW, origH, targetW, targetH, cropScale,
  )
  if (sEff <= sReq + 1e-9) return clampCropScale(cropScale)
  return clampCropScale(s0 / sEff)
}

/** Effective magnification vs base framing (1 = crop_scale 1 at a center-friendly focal). */
export function zoomFactor(focalX, focalY, origW, origH, targetW, targetH, cropScale) {
  if (!origW || !origH || !targetW || !targetH) return 1
  const { s0, sEff } = cropScales(
    focalX, focalY, origW, origH, targetW, targetH, cropScale,
  )
  if (!s0) return 1
  return sEff / s0
}

/** Port of aligner_core.compute_crop_frame — requested box; may leave the image. */
export function computeCropFrame(focalX, focalY, origW, origH, targetW, targetH, cropScale = DEFAULT_CROP_SCALE) {
  if (!origW || !origH || !targetW || !targetH) {
    return { x: 0, y: 0, w: 1, h: 1 }
  }
  const { fx, fy, sReq } = cropScales(focalX, focalY, origW, origH, targetW, targetH, cropScale)
  const w = Math.max(1, targetW / sReq)
  const h = Math.max(1, targetH / sReq)
  return {
    x: Math.round(fx - w / 2),
    y: Math.round(fy - h / 2),
    w: Math.round(w),
    h: Math.round(h),
  }
}

/** Port of aligner_core.compute_crop — effective in-bounds sample for Preview/export. */
export function computeCrop(focalX, focalY, origW, origH, targetW, targetH, cropScale = DEFAULT_CROP_SCALE) {
  if (!origW || !origH || !targetW || !targetH) {
    return { x: 0, y: 0, w: 1, h: 1 }
  }
  const { fx, fy, sEff, wFit, hFit } = cropScales(
    focalX, focalY, origW, origH, targetW, targetH, cropScale,
  )
  let w = Math.max(1, targetW / sEff)
  let h = Math.max(1, targetH / sEff)
  if (w > wFit + 1e-6 || h > hFit + 1e-6) {
    w = wFit
    h = hFit
  }
  let x = fx - w / 2
  let y = fy - h / 2
  x = Math.min(Math.max(x, 0), Math.max(0, origW - w))
  y = Math.min(Math.max(y, 0), Math.max(0, origH - h))
  return {
    x: Math.round(x),
    y: Math.round(y),
    w: Math.round(w),
    h: Math.round(h),
  }
}

/** Port of aligner_core.crop_to_widget. */
export function cropToWidget(cropX, cropY, cropW, cropH, dispW, dispH, origW, origH) {
  const sx = origW ? dispW / origW : 1
  const sy = origH ? dispH / origH : 1
  return {
    x: cropX * sx,
    y: cropY * sy,
    w: cropW * sx,
    h: cropH * sy,
  }
}

export function targetForMode(session) {
  const landscape = session?.alignment_mode !== 'portrait'
  return landscape
    ? { w: session.target_width, h: session.target_height }
    : { w: session.target_height, h: session.target_width }
}

/** Multiplicative wheel helper for crop_scale. deltaY < 0 zooms in (smaller box). */
export function nudgeCropScale(cropScale, deltaY, factor = 1.08) {
  const next = deltaY < 0 ? cropScale / factor : cropScale * factor
  return clampCropScale(next)
}

/** Draw a rule-of-thirds grid into a canvas context. */
export function drawRuleOfThirds(ctx, width, height, { color = 'rgba(255,255,255,0.85)', lineWidth = 2 } = {}) {
  if (!width || !height) return
  ctx.save()
  // Soft shadow behind lines for contrast on light/dark regions
  ctx.strokeStyle = 'rgba(0, 0, 0, 0.45)'
  ctx.lineWidth = lineWidth + 2
  ctx.beginPath()
  for (const t of [1 / 3, 2 / 3]) {
    const x = width * t
    const y = height * t
    ctx.moveTo(x, 0)
    ctx.lineTo(x, height)
    ctx.moveTo(0, y)
    ctx.lineTo(width, y)
  }
  ctx.stroke()
  ctx.strokeStyle = color
  ctx.lineWidth = lineWidth
  ctx.beginPath()
  for (const t of [1 / 3, 2 / 3]) {
    const x = width * t
    const y = height * t
    ctx.moveTo(x, 0)
    ctx.lineTo(x, height)
    ctx.moveTo(0, y)
    ctx.lineTo(width, y)
  }
  ctx.stroke()
  ctx.restore()
}

/**
 * Draw a B&W composition mask into a destination rect.
 * White (or inverted) regions are filled with a translucent guide color.
 * `fit`: 'contain' | 'cover' — keep mask aspect ratio, centered in the box.
 */
export function drawCompositionMask(ctx, maskImage, dx, dy, dw, dh, {
  invert = false,
  opacity = 0.5,
  color = '255, 220, 60',
  fit = 'contain',
} = {}) {
  if (!maskImage || !dw || !dh) return
  const tw = Math.max(1, Math.round(dw))
  const th = Math.max(1, Math.round(dh))
  const mw = maskImage.naturalWidth || maskImage.width || 0
  const mh = maskImage.naturalHeight || maskImage.height || 0
  if (!mw || !mh) return

  const scale = fit === 'cover'
    ? Math.max(tw / mw, th / mh)
    : Math.min(tw / mw, th / mh)
  const rw = mw * scale
  const rh = mh * scale
  const ox = (tw - rw) / 2
  const oy = (th - rh) / 2

  const off = document.createElement('canvas')
  off.width = tw
  off.height = th
  const octx = off.getContext('2d')
  octx.clearRect(0, 0, tw, th)
  octx.drawImage(maskImage, ox, oy, rw, rh)
  const imageData = octx.getImageData(0, 0, tw, th)
  const data = imageData.data
  const alpha = Math.round(Math.max(0, Math.min(1, opacity)) * 255)
  const [r, g, b] = color.split(',').map((v) => Number(v.trim()))
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 8) {
      data[i + 3] = 0
      continue
    }
    const lum = (data[i] + data[i + 1] + data[i + 2]) / 3
    const on = invert ? lum < 128 : lum >= 128
    if (on) {
      data[i] = r
      data[i + 1] = g
      data[i + 2] = b
      data[i + 3] = alpha
    } else {
      data[i + 3] = 0
    }
  }
  octx.putImageData(imageData, 0, 0)
  ctx.save()
  ctx.drawImage(off, dx, dy, dw, dh)
  ctx.restore()
}
