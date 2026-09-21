import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { SortableContext, arrayMove, rectSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { api, mediaUrl, readSse } from './api.js'
import {
  computeCrop,
  computeCropFrame,
  cropToWidget,
  nudgeCropScale,
  bakeCropScale,
  zoomFactor,
  targetForMode,
  DEFAULT_CROP_SCALE,
  clampCropScale,
  transformFocalForFlips,
  sourceCropForFlips,
  drawRuleOfThirds,
  drawCompositionMask,
} from './crop.js'
import { SIZE_RATIOS, matchRatio, sizeLabel } from './presets.js'

const PAGE_SIZE = 10
const COLS_KEY = 'fpa-original-cols'
const GRID_KEY = 'fpa-show-grid'
const ARRANGE_ZOOM_KEY = 'fpa-arrange-zoom'
const DEFAULT_COLS = [16, 68, 16]
const RIGHT_DOUBLE_MS = 400

/** Keys active on every tab. */
const HOTKEYS_SHARED = new Set(['ArrowLeft', 'ArrowRight', 'x', 'X', 'p', 'P', 'o', 'O', 'a', 'A', 'e', 'E', 'Escape', 'r', 'R'])
/** Extra keys on Original. */
const HOTKEYS_ORIGINAL = new Set(['Enter', ' ', 'Delete', 'Backspace', 'h', 'H', 'g', 'G', 'i', 'I', 'd', 'D'])
/** Extra keys on Preview. */
const HOTKEYS_PREVIEW = new Set(['c', 'C', 'Enter', '<', '>', ',', '.'])
/** Extra keys on Arrange. */
const HOTKEYS_ARRANGE = new Set(['c', 'C', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'])
const PREVIEW_WRAP_KEY = 'fpa-preview-wrap'
const MASK_FIT_KEY = 'fpa-mask-fit'

function hotkeyAllowed(tab, key) {
  if (HOTKEYS_SHARED.has(key)) return true
  if (tab === 'original') return HOTKEYS_ORIGINAL.has(key)
  if (tab === 'preview') return HOTKEYS_PREVIEW.has(key)
  if (tab === 'arrange') return HOTKEYS_ARRANGE.has(key)
  return false
}

function focalFromImage(img, pending) {
  if (pending && (pending.index == null || pending.index === img?.id)) return pending
  const cropScale = clampCropScale(img.crop_scale ?? DEFAULT_CROP_SCALE)
  return img.focal
    ? { x: img.focal[0], y: img.focal[1], autoCenter: Boolean(img.auto_center || img.focal_at_center), cropScale }
    : { x: img.width / 2, y: img.height / 2, autoCenter: true, cropScale }
}

function withCropScale(pt, img, pending) {
  const base = (pending && (pending.index == null || pending.index === img?.id)) ? pending : null
  return {
    ...pt,
    index: img?.id,
    cropScale: clampCropScale(
      pt.cropScale ?? base?.cropScale ?? img?.crop_scale ?? DEFAULT_CROP_SCALE,
    ),
  }
}

function formatBytes(n) {
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function dpiLabel(dpi) {
  if (!Array.isArray(dpi) || !dpi[0]) return null
  const x = Math.round(dpi[0])
  const y = Math.round(dpi[1] || dpi[0])
  return x === y ? `${x} DPI` : `${x}×${y} DPI`
}

function useDismissableOpen(initial = false) {
  const [open, setOpen] = useState(initial)
  const rootRef = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const onPointer = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer, true)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('pointerdown', onPointer, true)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [open])
  return [open, setOpen, rootRef]
}

/** Move a multi-selection as one block to the drop target (preserves relative order). */
function reorderMulti(order, selectedSet, activeId, overId) {
  if (!selectedSet.has(activeId) || selectedSet.size <= 1) {
    const from = order.indexOf(activeId)
    const to = order.indexOf(overId)
    if (from < 0 || to < 0) return order
    return arrayMove(order, from, to)
  }
  const selected = order.filter((id) => selectedSet.has(id))
  const without = order.filter((id) => !selectedSet.has(id))
  const activeIdx = order.indexOf(activeId)
  const overIdx = order.indexOf(overId)
  let insertAt = without.indexOf(overId)
  if (insertAt < 0) {
    insertAt = order.slice(0, overIdx).filter((id) => !selectedSet.has(id)).length
  } else if (activeIdx < overIdx) {
    insertAt += 1
  }
  return [...without.slice(0, insertAt), ...selected, ...without.slice(insertAt)]
}

function SortableThumb({
  id, img, selected, current, multiCount, onSelect, onOpen, onDiscard,
  view, orientation, targetW = 2560, targetH = 1440,
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.45 : 1 }
  const aligned = view === 'aligned'
  const fh = img.flip_h ? 1 : 0
  const fv = img.flip_v ? 1 : 0
  const src = aligned && img.focal
    ? mediaUrl('preview', img.id, `?orientation=${orientation || 'landscape'}&f=${img.focal[0]}-${img.focal[1]}&s=${img.crop_scale ?? 1}&n=${encodeURIComponent(img.filename)}&tw=${targetW}&th=${targetH}&fh=${fh}&fv=${fv}`)
    : mediaUrl('thumb', img.id, `?n=${encodeURIComponent(img.filename)}`)
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`thumb ${selected ? 'selected' : ''} ${current ? 'current' : ''} ${img.completed ? 'done' : ''} ${aligned && !img.focal ? 'no-focal' : ''}`}
      onClick={(e) => onSelect(e, img.id, img.filename)}
      onDoubleClick={() => onOpen(img.id)}
      onPointerDownCapture={(e) => {
        if (e.button === 1) {
          e.preventDefault()
          e.stopPropagation()
          if (e.shiftKey && onDiscard) onDiscard(img.id)
        }
      }}
      onAuxClick={(e) => {
        if (e.button === 1) {
          e.preventDefault()
          e.stopPropagation()
        }
      }}
      {...attributes}
      {...listeners}
    >
      <img src={src} alt={img.filename} loading="lazy" draggable={false} />
      <span className="idx">{img.id + 1}</span>
      {isDragging && multiCount > 1 && <span className="thumb-multi-badge">{multiCount}</span>}
      {aligned && !img.focal && <span className="thumb-note">no focal</span>}
    </div>
  )
}

function NavDots({ session, onGo }) {
  const total = session.total
  const current = session.current_idx
  const page = Math.floor(current / PAGE_SIZE)
  const start = page * PAGE_SIZE
  const count = Math.min(PAGE_SIZE, total - start)
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  return (
    <div className="nav-dots" role="navigation" aria-label="Images">
      {pages > 1 && (
        <div className="dot-pages" aria-label="Pages">
          {Array.from({ length: pages }, (_, p) => (
            <button
              key={p}
              type="button"
              className={`page-chip ${p === page ? 'current' : ''}`}
              title={`Page ${p + 1} (images ${p * PAGE_SIZE + 1}–${Math.min(total, (p + 1) * PAGE_SIZE)})`}
              onClick={() => onGo(p * PAGE_SIZE)}
            >
              {p + 1}
            </button>
          ))}
        </div>
      )}
      <div className="dot-row" aria-label="Images on this page">
        {Array.from({ length: count }, (_, i) => {
          const idx = start + i
          const im = session.images[idx]
          const center = Boolean(im?.auto_center || im?.focal_at_center)
          const cls = [
            'dot',
            idx === current ? 'current' : '',
            im?.completed && center ? 'center' : '',
            im?.completed && !center ? 'done' : '',
          ].filter(Boolean).join(' ')
          const state = !im?.completed ? 'no focal' : center ? 'center (unshifted)' : 'focal set'
          return (
            <button
              key={im?.filename || idx}
              type="button"
              className={cls}
              title={`${idx + 1}. ${im?.filename || ''} — ${state}`}
              onClick={() => onGo(idx)}
            />
          )
        })}
      </div>
    </div>
  )
}

function Hotkey({ kbd, label, onClick, danger, disabled }) {
  return (
    <button
      type="button"
      className={`hotkey ${danger ? 'danger' : ''} ${disabled ? 'disabled' : ''}`}
      onClick={onClick}
      disabled={disabled}
      title={`${label} (${kbd})${disabled ? ' — unavailable' : ''}`}
    >
      <span className="hotkey-kbd">{kbd}</span>
      <span className="hotkey-label">{label}</span>
    </button>
  )
}

function SizePanel({ width, height, onApply }) {
  const [open, setOpen, rootRef] = useDismissableOpen(false)
  const [manualW, setManualW] = useState(width)
  const [manualH, setManualH] = useState(height)
  const [pickedRatio, setPickedRatio] = useState(null)
  const ratioId = pickedRatio || matchRatio(width, height)
  const ratioLabel = ratioId || 'Custom'
  const ratioPreset = SIZE_RATIOS.find((r) => r.id === ratioId) || null

  useEffect(() => {
    setManualW(width)
    setManualH(height)
    setPickedRatio(null)
  }, [width, height])

  return (
    <div className="image-facts size-panel" ref={rootRef}>
      <button type="button" className="facts-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open} title="Target size">
        <span className="facts-role">Size</span>
        <span>{ratioLabel} · {width}×{height}</span>
        <span className="facts-caret" aria-hidden="true">{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div className="facts-panel size-facts-panel">
          <div>
            <div className="panel-section-label">Ratio</div>
            <div className="row wrap">
              {SIZE_RATIOS.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  className={ratioId === r.id ? '' : 'secondary'}
                  onClick={() => {
                    setPickedRatio(r.id)
                    const match = r.sizes.find(([w, h]) => w === Number(width) && h === Number(height))
                    const [w, h] = match || r.sizes[Math.min(1, r.sizes.length - 1)]
                    onApply(w, h)
                  }}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="panel-section-label">Resolution</div>
            <div className="row wrap">
              {(ratioPreset ? ratioPreset.sizes : SIZE_RATIOS.flatMap((r) => r.sizes)).map(([w, h]) => (
                <button
                  key={`${w}x${h}`}
                  type="button"
                  className={w === Number(width) && h === Number(height) ? '' : 'secondary'}
                  onClick={() => onApply(w, h)}
                >
                  {sizeLabel([w, h])}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="panel-section-label">Manual</div>
            <div className="row">
              <label>W <input type="number" min={1} value={manualW} onChange={(e) => setManualW(e.target.value)} /></label>
              <label>H <input type="number" min={1} value={manualH} onChange={(e) => setManualH(e.target.value)} /></label>
              <button
                type="button"
                onClick={() => {
                  const w = Number(manualW)
                  const h = Number(manualH)
                  if (w >= 1 && h >= 1) onApply(w, h)
                }}
              >
                Apply
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function OverlayPanel({
  showGrid, setShowGrid,
  maskImage, showMask, setShowMask,
  maskInvert, setMaskInvert,
  maskHalfOpacity, setMaskHalfOpacity,
  maskFit, setMaskFit,
  onPickMask,
}) {
  const [open, setOpen, rootRef] = useDismissableOpen(false)
  const bits = []
  if (showGrid) bits.push('Grid')
  if (showMask) bits.push(maskInvert ? 'Mask↕' : 'Mask')
  if (showMask) bits.push(maskFit === 'cover' ? 'Cover' : 'Contain')
  if (showMask && maskHalfOpacity) bits.push('50%')
  else if (showMask) bits.push('100%')
  const summary = bits.length ? bits.join(' · ') : 'Guides off'

  return (
    <div className="image-facts overlay-panel" ref={rootRef}>
      <button type="button" className="facts-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open} title="Composition guides">
        <span className="facts-role">Guides</span>
        <span>{summary}</span>
        <span className="facts-caret" aria-hidden="true">{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div className="facts-panel overlay-facts-panel">
          {maskImage ? (
            <div className="mask-thumb-wrap">
              <img className="mask-thumb" src={maskImage.src} alt="Composition mask" />
              <span className="muted">Mask preview</span>
            </div>
          ) : (
            <p className="muted">No mask loaded — upload a black &amp; white image (white = guide).</p>
          )}
          <div className="row wrap">
            <button type="button" className="secondary" onClick={onPickMask}>Upload mask…</button>
            <button
              type="button"
              aria-pressed={showGrid}
              className={showGrid ? '' : 'secondary'}
              onClick={() => setShowGrid((v) => !v)}
            >
              Grid {showGrid ? 'On' : 'Off'}
            </button>
            <button
              type="button"
              aria-pressed={showMask}
              className={showMask ? '' : 'secondary'}
              disabled={!maskImage}
              onClick={() => setShowMask((v) => !v)}
            >
              Mask {showMask ? 'On' : 'Off'}
            </button>
            <button
              type="button"
              aria-pressed={maskFit === 'contain'}
              className={maskFit === 'contain' ? '' : 'secondary'}
              disabled={!maskImage}
              onClick={() => setMaskFit('contain')}
              title="Fit entire mask inside the crop (letterbox)"
            >
              Contain
            </button>
            <button
              type="button"
              aria-pressed={maskFit === 'cover'}
              className={maskFit === 'cover' ? '' : 'secondary'}
              disabled={!maskImage}
              onClick={() => setMaskFit('cover')}
              title="Fill the crop with the mask (may crop edges)"
            >
              Cover
            </button>
            <button
              type="button"
              aria-pressed={maskInvert}
              className={maskInvert ? '' : 'secondary'}
              disabled={!maskImage}
              onClick={() => setMaskInvert((v) => !v)}
            >
              Invert
            </button>
            <button
              type="button"
              aria-pressed={maskHalfOpacity}
              className={maskHalfOpacity ? '' : 'secondary'}
              disabled={!maskImage}
              onClick={() => setMaskHalfOpacity((v) => !v)}
            >
              {maskHalfOpacity ? 'Opacity 50%' : 'Opacity 100%'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function ImageFacts({ img, pending }) {
  const [open, setOpen, rootRef] = useDismissableOpen(false)
  const [pathExpanded, setPathExpanded] = useState(false)
  const [copied, setCopied] = useState(false)
  const copyTimer = useRef(null)

  useEffect(() => {
    setPathExpanded(false)
    setCopied(false)
  }, [img?.id, img?.path])

  useEffect(() => () => {
    if (copyTimer.current) clearTimeout(copyTimer.current)
  }, [])

  if (!img) return null
  const mp = img.megapixels || (img.width && img.height ? (img.width * img.height) / 1e6 : 0)
  const dpi = dpiLabel(img.dpi)
  const focal = pending || (img.focal ? { x: img.focal[0], y: img.focal[1] } : null)

  function toggleOpen() {
    setOpen((v) => {
      if (v) {
        setPathExpanded(false)
        setCopied(false)
      }
      return !v
    })
  }

  async function onPathClick() {
    if (!pathExpanded) {
      setPathExpanded(true)
      return
    }
    try {
      await navigator.clipboard.writeText(img.path)
      setCopied(true)
      if (copyTimer.current) clearTimeout(copyTimer.current)
      copyTimer.current = setTimeout(() => setCopied(false), 1400)
    } catch {
      /* ignore clipboard failures */
    }
  }

  return (
    <div className="image-facts" ref={rootRef}>
      <button type="button" className="facts-toggle" onClick={toggleOpen} aria-expanded={open} title="Image details">
        <span className="facts-role">Details</span>
        <span>{img.width} × {img.height} px{mp ? ` · ${Number(mp).toFixed(1)} MP` : ''}{dpi ? ` · ${dpi}` : ''}</span>
        <span className="facts-caret" aria-hidden="true">{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <dl className="facts-panel">
          <div><dt>File</dt><dd className="facts-filename">{img.filename}</dd></div>
          <div><dt>Pixels</dt><dd>{img.width.toLocaleString()} × {img.height.toLocaleString()} ({Number(mp).toFixed(2)} MP)</dd></div>
          <div><dt>DPI</dt><dd>{dpi || 'not tagged'}</dd></div>
          <div><dt>Size</dt><dd>{formatBytes(img.bytes)}</dd></div>
          <div><dt>Format</dt><dd>{(img.format || '—').toUpperCase()}{img.mode ? ` · ${img.mode}` : ''}</dd></div>
          <div><dt>EXIF orientation</dt><dd>{img.orientation || 1}</dd></div>
          <div><dt>Focal</dt><dd>{focal ? `${Math.round(focal.x)}, ${Math.round(focal.y)}${pending ? ' (pending)' : ''}` : 'not set'}</dd></div>
          <div><dt>Crop scale</dt><dd>{clampCropScale(pending?.cropScale ?? img.crop_scale ?? DEFAULT_CROP_SCALE).toFixed(2)}×</dd></div>
          <div>
            <dt>Path</dt>
            <dd>
              <button
                type="button"
                className={`facts-path ${pathExpanded ? 'expanded' : ''} ${copied ? 'copied' : ''}`}
                onClick={onPathClick}
                title={pathExpanded ? 'Click to copy path' : 'Click to show full path'}
              >
                {img.path}
              </button>
              {copied && <span className="facts-copied">Copied</span>}
            </dd>
          </div>
        </dl>
      )}
    </div>
  )
}

function useColumnLayout() {
  const [cols, setCols] = useState(() => {
    try {
      const raw = localStorage.getItem(COLS_KEY)
      const parsed = raw ? JSON.parse(raw) : null
      if (Array.isArray(parsed) && parsed.length === 3) return parsed
    } catch { /* ignore */ }
    return DEFAULT_COLS
  })
  useEffect(() => {
    localStorage.setItem(COLS_KEY, JSON.stringify(cols))
  }, [cols])
  return [cols, setCols]
}

function useShowGrid() {
  const [showGrid, setShowGrid] = useState(() => {
    try {
      return localStorage.getItem(GRID_KEY) === '1'
    } catch {
      return false
    }
  })
  useEffect(() => {
    localStorage.setItem(GRID_KEY, showGrid ? '1' : '0')
  }, [showGrid])
  return [showGrid, setShowGrid]
}

function useArrangeZoom() {
  const [zoom, setZoom] = useState(() => {
    try {
      const n = Number(localStorage.getItem(ARRANGE_ZOOM_KEY))
      if (Number.isFinite(n)) return Math.min(2, Math.max(0.6, n))
    } catch { /* ignore */ }
    return 1
  })
  useEffect(() => {
    localStorage.setItem(ARRANGE_ZOOM_KEY, String(zoom))
  }, [zoom])
  const nudge = (delta) => setZoom((z) => Math.min(2, Math.max(0.6, Math.round((z + delta) * 10) / 10)))
  return [zoom, nudge]
}

function SplitHandle({ onBegin, onDrag }) {
  return (
    <div
      className="split-handle"
      role="separator"
      aria-orientation="vertical"
      onMouseDown={(e) => {
        e.preventDefault()
        const startX = e.clientX
        onBegin()
        const move = (ev) => onDrag(ev.clientX - startX)
        const up = () => {
          window.removeEventListener('mousemove', move)
          window.removeEventListener('mouseup', up)
        }
        window.addEventListener('mousemove', move)
        window.addEventListener('mouseup', up)
      }}
    />
  )
}

function SidePane({ img, label, onOpen }) {
  if (!img) {
    return (
      <div className="side-thumb empty">
        <span className="muted">{label}</span>
      </div>
    )
  }
  const src = img.media_kind === 'video'
    ? mediaUrl('frame', img.id, `?frame=${img.work_frame ?? 0}&n=${encodeURIComponent(img.filename)}&wf=${img.work_frame ?? 0}`)
    : mediaUrl('original', img.id, `?n=${encodeURIComponent(img.filename)}`)
  return (
    <button type="button" className="side-thumb" onClick={onOpen} title={`Go to ${img.filename}`}>
      <span className="side-label">{label}</span>
      <span className="side-frame">
        <img src={src} alt={img.filename} />
      </span>
      <span className="side-name">{img.filename}</span>
    </button>
  )
}

function originalStageSrc(img) {
  if (!img) return ''
  if (img.media_kind === 'video') {
    const wf = img.work_frame ?? 0
    return mediaUrl('frame', img.id, `?frame=${wf}&n=${encodeURIComponent(img.filename)}&wf=${wf}`)
  }
  return mediaUrl('original', img.id, `?n=${encodeURIComponent(img.filename)}`)
}

function VideoScrubber({ img, onSession, onLocalWork, onError }) {
  const [busy, setBusy] = useState(false)
  const [splitPrompt, setSplitPrompt] = useState(null) // { atFrame }
  const [localWork, setLocalWork] = useState(img?.work_frame ?? 0)
  useEffect(() => {
    setLocalWork(img?.work_frame ?? 0)
  }, [img?.id, img?.work_frame, img?.filename])

  if (!img || img.media_kind !== 'video') return null
  const frameCount = Math.max(1, img.frame_count || 1)
  const inF = img.in_frame ?? 0
  const outF = img.out_frame ?? frameCount - 1
  const work = localWork
  const maxFrame = frameCount - 1

  async function patchRange(partial) {
    setBusy(true)
    try {
      const next = await api.videoRange({ index: img.id, ...partial })
      onSession(next)
    } catch (err) {
      onError?.(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function onSetOut() {
    setBusy(true)
    try {
      const next = await api.videoRange({ index: img.id, out_frame: work, work_frame: work })
      onSession(next)
      setSplitPrompt({ atFrame: work })
    } catch (err) {
      onError?.(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function confirmTrim() {
    setSplitPrompt(null)
  }

  async function confirmSplit() {
    const at = splitPrompt?.atFrame ?? work
    setSplitPrompt(null)
    setBusy(true)
    try {
      const next = await api.videoSplit({ index: img.id, at_frame: at })
      onSession(next)
    } catch (err) {
      onError?.(err.message)
    } finally {
      setBusy(false)
    }
  }

  const inPct = (inF / Math.max(1, maxFrame)) * 100
  const outPct = (outF / Math.max(1, maxFrame)) * 100
  const workPct = (work / Math.max(1, maxFrame)) * 100

  return (
    <div className="video-scrubber">
      <div className="video-scrubber-track-wrap">
        <div className="video-scrubber-range" style={{ left: `${inPct}%`, width: `${Math.max(0, outPct - inPct)}%` }} />
        <input
          type="range"
          className="video-scrubber-input"
          min={0}
          max={maxFrame}
          value={work}
          disabled={busy}
          onChange={(e) => {
            const wf = Number(e.target.value)
            setLocalWork(wf)
            onLocalWork?.(wf)
          }}
          onPointerUp={(e) => patchRange({ work_frame: Number(e.currentTarget.value) })}
          onKeyUp={(e) => {
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'Home' || e.key === 'End') {
              patchRange({ work_frame: Number(e.currentTarget.value) })
            }
          }}
          aria-label="Work frame"
        />
        <div className="video-scrubber-playhead" style={{ left: `${workPct}%` }} />
      </div>
      <div className="video-scrubber-row">
        <button type="button" className="secondary" disabled={busy} onClick={() => patchRange({ in_frame: work, work_frame: work })}>
          Set In
        </button>
        <button type="button" className="secondary" disabled={busy} onClick={onSetOut}>
          Set Out
        </button>
        <span className="muted video-scrubber-meta">
          {work} / {maxFrame} · in {inF}–{outF}
          {img.fps ? ` · ${Number(img.fps).toFixed(1)} fps` : ''}
        </span>
      </div>
      {splitPrompt && (
        <div className="video-split-modal" role="dialog" aria-modal="true">
          <div className="video-split-card">
            <p>Out set at frame {splitPrompt.atFrame}. Trim only, or split the rest into a new clip?</p>
            <div className="video-split-actions">
              <button type="button" onClick={confirmTrim}>Trim</button>
              <button type="button" onClick={confirmSplit}>Split</button>
              <button type="button" className="secondary" onClick={() => setSplitPrompt(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function FocalStage({
  session, pending, setPending, onConfirm, onDiscard, showGrid,
  maskImage, showMask, maskInvert, maskHalfOpacity, maskFit,
}) {
  const canvasRef = useRef(null)
  const imgRef = useRef(null)
  const stageRef = useRef(null)
  const photoRef = useRef(null)
  const lastRight = useRef(0)
  const drag = useRef(null)
  const drawLatest = useRef(() => {})
  const pendingRef = useRef(pending)
  pendingRef.current = pending
  const img = session.images[session.current_idx]
  const focal = img ? focalFromImage(img, pending) : { x: 0, y: 0, cropScale: 1 }
  const stageSrc = originalStageSrc(img)

  function sourceSize() {
    const image = imgRef.current
    const srcW = image?.naturalWidth || 0
    const srcH = image?.naturalHeight || 0
    return {
      origW: srcW || img?.width || 1,
      origH: srcH || img?.height || 1,
    }
  }

  /** Photo box relative to the stage (for full-stage overlay mapping). */
  function photoLayout() {
    const stage = stageRef.current
    const photo = photoRef.current
    const image = imgRef.current
    if (!stage || !photo || !image) return null
    const stageRect = stage.getBoundingClientRect()
    const photoRect = photo.getBoundingClientRect()
    const dw = image.complete && image.naturalWidth > 0
      ? Math.max(1, Math.round(image.clientWidth))
      : 0
    const dh = image.complete && image.naturalWidth > 0
      ? Math.max(1, Math.round(image.clientHeight))
      : 0
    if (!dw || !dh) return null
    return {
      left: photoRect.left - stageRect.left,
      top: photoRect.top - stageRect.top,
      dw,
      dh,
      stageW: Math.max(1, Math.round(stage.clientWidth)),
      stageH: Math.max(1, Math.round(stage.clientHeight)),
    }
  }

  function draw() {
    const canvas = canvasRef.current
    const image = imgRef.current
    const stage = stageRef.current
    if (!img || !canvas || !image || !stage) return
    const layout = photoLayout()
    const stageW = Math.max(1, Math.round(stage.clientWidth))
    const stageH = Math.max(1, Math.round(stage.clientHeight))
    canvas.width = stageW
    canvas.height = stageH
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, stageW, stageH)
    const showOverlay = Boolean(pending || img.focal)
    if (!layout) return
    const { left, top, dw, dh } = layout
    if (!showOverlay) {
      if (showMask && maskImage) {
        drawCompositionMask(ctx, maskImage, left, top, dw, dh, {
          invert: maskInvert,
          opacity: maskHalfOpacity ? 0.5 : 0.72,
          fit: maskFit,
        })
      }
      if (showGrid) {
        ctx.save()
        ctx.translate(left, top)
        drawRuleOfThirds(ctx, dw, dh)
        ctx.restore()
      }
      return
    }
    const { origW, origH } = sourceSize()
    const target = targetForMode(session)
    const frame = computeCropFrame(focal.x, focal.y, origW, origH, target.w, target.h, focal.cropScale)
    const sample = computeCrop(focal.x, focal.y, origW, origH, target.w, target.h, focal.cropScale)
    const box = cropToWidget(frame.x, frame.y, frame.w, frame.h, dw, dh, origW, origH)
    const boxStage = { x: left + box.x, y: top + box.y, w: box.w, h: box.h }
    // Dim the photo; the crop box is filled with the Preview-equivalent sample.
    ctx.fillStyle = 'rgba(8, 8, 14, 0.55)'
    ctx.fillRect(left, top, dw, dh)
    if (boxStage.w > 0 && boxStage.h > 0 && sample.w > 0 && sample.h > 0) {
      ctx.save()
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'
      ctx.drawImage(
        image,
        sample.x, sample.y, sample.w, sample.h,
        boxStage.x, boxStage.y, boxStage.w, boxStage.h,
      )
      ctx.restore()
    }
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.95)'
    ctx.lineWidth = 2
    ctx.strokeRect(boxStage.x + 1, boxStage.y + 1, Math.max(0, boxStage.w - 2), Math.max(0, boxStage.h - 2))
    if (showMask && maskImage && boxStage.w > 0 && boxStage.h > 0) {
      drawCompositionMask(ctx, maskImage, boxStage.x, boxStage.y, boxStage.w, boxStage.h, {
        invert: maskInvert,
        opacity: maskHalfOpacity ? 0.5 : 0.72,
        fit: maskFit,
      })
    }
    if (showGrid && boxStage.w > 0 && boxStage.h > 0) {
      ctx.save()
      ctx.beginPath()
      ctx.rect(boxStage.x, boxStage.y, boxStage.w, boxStage.h)
      ctx.clip()
      ctx.translate(boxStage.x, boxStage.y)
      drawRuleOfThirds(ctx, boxStage.w, boxStage.h)
      ctx.restore()
    }
    const fx = left + (focal.x / origW) * dw
    const fy = top + (focal.y / origH) * dh
    ctx.strokeStyle = pending ? '#e67e22' : '#e74c3c'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(fx - 12, fy)
    ctx.lineTo(fx + 12, fy)
    ctx.moveTo(fx, fy - 12)
    ctx.lineTo(fx, fy + 12)
    ctx.stroke()
    ctx.beginPath()
    ctx.arc(fx, fy, 6, 0, Math.PI * 2)
    ctx.stroke()
  }
  drawLatest.current = draw

  useEffect(() => {
    drawLatest.current()
  })

  useEffect(() => {
    const redraw = () => drawLatest.current()
    const stage = stageRef.current
    const image = imgRef.current
    const canvas = canvasRef.current
    if (!stage) return undefined
    const ro = new ResizeObserver(redraw)
    ro.observe(stage)
    if (image) ro.observe(image)
    window.addEventListener('resize', redraw)
    const onWheel = (e) => {
      e.preventDefault()
      e.stopPropagation()
      if (!img) return
      const base = focalFromImage(img, pendingRef.current)
      setPending({
        ...base,
        index: img.id,
        autoCenter: false,
        cropScale: nudgeCropScale(base.cropScale ?? DEFAULT_CROP_SCALE, e.deltaY),
      })
    }
    canvas?.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', redraw)
      canvas?.removeEventListener('wheel', onWheel)
    }
  }, [img?.id, img?.filename, img, setPending])

  function toOrig(ev) {
    const layout = photoLayout()
    if (!layout || !img) return { x: 0, y: 0 }
    const stage = stageRef.current
    if (!stage) return { x: 0, y: 0 }
    const stageRect = stage.getBoundingClientRect()
    const { origW, origH } = sourceSize()
    const lx = ev.clientX - stageRect.left - layout.left
    const ly = ev.clientY - stageRect.top - layout.top
    const nx = lx / layout.dw
    const ny = ly / layout.dh
    return withCropScale({
      x: Math.max(0, Math.min(origW, nx * origW)),
      y: Math.max(0, Math.min(origH, ny * origH)),
      autoCenter: false,
    }, img, pendingRef.current)
  }

  function centerPending() {
    const { origW, origH } = sourceSize()
    return withCropScale({ x: origW / 2, y: origH / 2, autoCenter: true }, img, pendingRef.current)
  }

  if (!img) return null

  const pointerHandlers = {
    onDoubleClick: (e) => {
      if (e.button !== 0) return
      const pt = toOrig(e)
      setPending(pt)
      onConfirm(pt)
    },
    onContextMenu: (e) => e.preventDefault(),
    onPointerDown: (e) => {
      if (e.button === 1) {
        e.preventDefault()
        e.stopPropagation()
        if (e.shiftKey) onDiscard()
        return
      }
      if (e.button === 2) {
        e.preventDefault()
        const now = Date.now()
        const center = centerPending()
        if (now - lastRight.current < RIGHT_DOUBLE_MS) {
          lastRight.current = 0
          setPending(center)
          onConfirm(center)
        } else {
          lastRight.current = now
          setPending(center)
        }
        return
      }
      if (e.button !== 0) return
      e.preventDefault()
      const pt = toOrig(e)
      setPending(pt)
      drag.current = {
        pointerId: e.pointerId,
        x: e.clientX,
        y: e.clientY,
        moved: false,
      }
      try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* ignore */ }
    },
    onPointerMove: (e) => {
      if (!drag.current || drag.current.pointerId !== e.pointerId) return
      const dx = e.clientX - drag.current.x
      const dy = e.clientY - drag.current.y
      if (!drag.current.moved && (dx * dx + dy * dy) < 9) return
      drag.current.moved = true
      setPending(toOrig(e))
    },
    onPointerUp: (e) => {
      if (!drag.current || drag.current.pointerId !== e.pointerId) return
      try { e.currentTarget.releasePointerCapture(e.pointerId) } catch { /* ignore */ }
      drag.current = null
    },
    onPointerCancel: (e) => {
      if (!drag.current || drag.current.pointerId !== e.pointerId) return
      drag.current = null
    },
  }

  return (
    <div className="stage" ref={stageRef}>
      <div className="stage-photo" ref={photoRef}>
        <img
          ref={imgRef}
          className="full"
          src={stageSrc}
          alt=""
          draggable={false}
          onLoad={() => drawLatest.current()}
        />
      </div>
      <canvas ref={canvasRef} className="stage-overlay" {...pointerHandlers} />
    </div>
  )
}

function PreviewStage({
  session, onCommit, onError, showGrid, draftFlushRef,
  maskImage, showMask, maskInvert, maskHalfOpacity, maskFit,
  wrapNav, setWrapNav, compareApiRef,
}) {
  const viewportRef = useRef(null)
  const stageRef = useRef(null)
  const canvasRef = useRef(null)
  const imgRef = useRef(null)
  const drag = useRef(null)
  const drawLatest = useRef(() => {})
  const loadGenRef = useRef(0)
  const img = session.images[session.current_idx]
  const prevImg = session.images[session.current_idx - 1]
  const nextImg = session.images[session.current_idx + 1]
  const sourceSrc = img
    ? (img.media_kind === 'video'
      ? mediaUrl('frame', img.id, `?frame=${img.work_frame ?? 0}&n=${encodeURIComponent(img.filename)}&wf=${img.work_frame ?? 0}`)
      : mediaUrl('original', img.id, `?n=${encodeURIComponent(img.filename)}`))
    : ''
  const committed = useMemo(() => ({
    x: img?.focal?.[0] ?? (img?.width || 0) / 2,
    y: img?.focal?.[1] ?? (img?.height || 0) / 2,
    cropScale: clampCropScale(img?.crop_scale ?? DEFAULT_CROP_SCALE),
    flipH: Boolean(img?.flip_h),
    flipV: Boolean(img?.flip_v),
  }), [img])
  const [draft, setDraft] = useState(committed)
  const [compare, setCompare] = useState(false)
  // -1 = previous fully on top, 0 = current only, +1 = next fully on top
  const [neighbor, setNeighbor] = useState(0)
  const [committing, setCommitting] = useState(false)
  const [focalPulse, setFocalPulse] = useState(0)
  const [sourceReady, setSourceReady] = useState(false)

  function nudgeNeedFocal() {
    if (img?.focal) return
    setFocalPulse((n) => n + 1)
  }

  function clearCanvas() {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, canvas.width || 0, canvas.height || 0)
  }

  useEffect(() => {
    loadGenRef.current += 1
    const token = loadGenRef.current
    setSourceReady(false)
    clearCanvas()
    const check = () => {
      if (token !== loadGenRef.current) return
      const image = imgRef.current
      if (!image) return
      let matches = false
      try {
        const abs = new URL(sourceSrc, window.location.href).href
        matches = image.currentSrc === abs || image.src === abs || image.getAttribute('src') === sourceSrc
      } catch {
        matches = image.getAttribute('src') === sourceSrc
      }
      if (matches && image.complete && image.naturalWidth) {
        setSourceReady(true)
        drawLatest.current()
      }
    }
    requestAnimationFrame(check)
  }, [img?.id, sourceSrc])

  useEffect(() => {
    setDraft(committed)
    setCompare(false)
    setNeighbor(0)
    setFocalPulse(0)
  }, [img?.id, committed.x, committed.y, committed.cropScale, committed.flipH, committed.flipV])

  const view = compare ? committed : draft
  const dirty = Boolean(img?.focal) && (
    Math.abs(draft.x - committed.x) > 0.5
    || Math.abs(draft.y - committed.y) > 0.5
    || Math.abs(draft.cropScale - committed.cropScale) > 0.001
    || Boolean(draft.flipH) !== Boolean(committed.flipH)
    || Boolean(draft.flipV) !== Boolean(committed.flipV)
  )

  async function commit() {
    if (!img || !dirty || committing) return
    setCommitting(true)
    try {
      await onCommit({
        x: draft.x,
        y: draft.y,
        cropScale: draft.cropScale,
        flipH: Boolean(draft.flipH),
        flipV: Boolean(draft.flipV),
        autoCenter: false,
      })
      setCompare(false)
    } catch (err) {
      onError?.(err.message || String(err))
    } finally {
      setCommitting(false)
    }
  }

  const commitRef = useRef(commit)
  commitRef.current = commit

  function stepNeighbor(delta) {
    setNeighbor((n) => {
      let next = Math.round((n + delta) * 10) / 10
      next = Math.max(-1, Math.min(1, next))
      if (!prevImg && next < 0) next = 0
      if (!nextImg && next > 0) next = 0
      return next
    })
  }

  const stepNeighborRef = useRef(stepNeighbor)
  stepNeighborRef.current = stepNeighbor

  useEffect(() => {
    if (!compareApiRef) return undefined
    compareApiRef.current = {
      dirty,
      compare,
      canToggle: dirty,
      canCommit: dirty && !compare && !committing,
      toggle: () => {
        if (!dirty) return false
        setCompare((v) => !v)
        return true
      },
      commit: () => {
        if (!dirty || compare || committing) return false
        commitRef.current?.()
        return true
      },
      stepNeighbor: (delta) => {
        stepNeighborRef.current?.(delta)
        return true
      },
      nudgeNeedFocal: () => {
        if (img?.focal) return false
        setFocalPulse((n) => n + 1)
        return true
      },
    }
    return () => {
      if (compareApiRef) compareApiRef.current = null
    }
  }, [dirty, compare, committing, compareApiRef, img?.focal])

  useEffect(() => {
    if (!draftFlushRef) return undefined
    if (dirty && img) {
      draftFlushRef.current = {
        x: draft.x,
        y: draft.y,
        cropScale: draft.cropScale,
        flipH: Boolean(draft.flipH),
        flipV: Boolean(draft.flipV),
        autoCenter: false,
        index: img.id,
      }
    } else {
      draftFlushRef.current = null
    }
    return () => {
      if (draftFlushRef) draftFlushRef.current = null
    }
  }, [dirty, draft.x, draft.y, draft.cropScale, draft.flipH, draft.flipV, img, draftFlushRef])

  function applyDraftScale(nextScale, x, y) {
    const image = imgRef.current
    if (!image?.naturalWidth) return clampCropScale(nextScale)
    const target = targetForMode(session)
    return bakeCropScale(
      x, y, image.naturalWidth, image.naturalHeight,
      target.w, target.h, clampCropScale(nextScale),
    )
  }

  function sourceMatches() {
    const image = imgRef.current
    if (!image || !sourceSrc) return false
    try {
      return image.currentSrc === new URL(sourceSrc, window.location.href).href
        || image.src === new URL(sourceSrc, window.location.href).href
        || image.getAttribute('src') === sourceSrc
    } catch {
      return image.getAttribute('src') === sourceSrc
    }
  }

  function draw() {
    const canvas = canvasRef.current
    const image = imgRef.current
    const viewport = viewportRef.current
    const stage = stageRef.current
    if (!img || !canvas || !image || !viewport || !stage) return
    if (!sourceReady || !sourceMatches() || !image.complete || !image.naturalWidth) {
      clearCanvas()
      return
    }
    const target = targetForMode(session)
    const maxW = Math.max(1, viewport.clientWidth)
    const maxH = Math.max(1, viewport.clientHeight)
    const fit = Math.min(maxW / target.w, maxH / target.h)
    const dw = Math.max(1, Math.round(target.w * fit))
    const dh = Math.max(1, Math.round(target.h * fit))
    canvas.width = dw
    canvas.height = dh
    canvas.style.width = `${dw}px`
    canvas.style.height = `${dh}px`
    stage.style.width = `${dw}px`
    stage.style.height = `${dh}px`
    const w = image.naturalWidth
    const h = image.naturalHeight
    const flipped = transformFocalForFlips(view.x, view.y, w, h, view.flipH, view.flipV)
    const crop = computeCrop(
      flipped.x, flipped.y, w, h,
      target.w, target.h, view.cropScale,
    )
    const src = sourceCropForFlips(crop, w, h, view.flipH, view.flipV)
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, dw, dh)
    ctx.drawImage(image, src.x, src.y, src.w, src.h, 0, 0, dw, dh)
    if (showMask && maskImage) {
      drawCompositionMask(ctx, maskImage, 0, 0, dw, dh, {
        invert: maskInvert,
        opacity: maskHalfOpacity ? 0.5 : 0.72,
        fit: maskFit,
      })
    }
    if (showGrid) {
      drawRuleOfThirds(ctx, dw, dh)
    }
  }
  drawLatest.current = draw

  useEffect(() => { drawLatest.current() })

  useEffect(() => {
    const redraw = () => drawLatest.current()
    const viewport = viewportRef.current
    const stage = stageRef.current
    if (!viewport) return undefined
    const ro = new ResizeObserver(redraw)
    ro.observe(viewport)
    window.addEventListener('resize', redraw)
    const onWheelNative = (e) => {
      if (!img?.focal) {
        e.preventDefault()
        nudgeNeedFocal()
        return
      }
      if (compare) return
      e.preventDefault()
      setDraft((d) => {
        const next = nudgeCropScale(d.cropScale, e.deltaY)
        return { ...d, cropScale: applyDraftScale(next, d.x, d.y) }
      })
      setCompare(false)
    }
    stage?.addEventListener('wheel', onWheelNative, { passive: false })
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', redraw)
      stage?.removeEventListener('wheel', onWheelNative)
    }
  }, [img?.id, img?.focal, compare])

  useEffect(() => {
    const onKey = (e) => {
      if (e.target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return
      if (e.key === '<' || e.key === ',') {
        e.preventDefault()
        stepNeighborRef.current?.(-0.1)
      } else if (e.key === '>' || e.key === '.') {
        e.preventDefault()
        stepNeighborRef.current?.(0.1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function panBy(dx, dy) {
    const canvas = canvasRef.current
    const image = imgRef.current
    if (!canvas || !image?.naturalWidth) return
    const target = targetForMode(session)
    const w = image.naturalWidth
    const h = image.naturalHeight
    const flipped = transformFocalForFlips(draft.x, draft.y, w, h, draft.flipH, draft.flipV)
    const crop = computeCrop(
      flipped.x, flipped.y, w, h,
      target.w, target.h, draft.cropScale,
    )
    const sx = crop.w / canvas.clientWidth
    const sy = crop.h / canvas.clientHeight
    let panDx = dx
    let panDy = dy
    if (draft.flipH) panDx = -panDx
    if (draft.flipV) panDy = -panDy
    setDraft((d) => {
      const x = Math.max(0, Math.min(w, d.x - panDx * sx))
      const y = Math.max(0, Math.min(h, d.y - panDy * sy))
      return {
        ...d,
        x,
        y,
        cropScale: bakeCropScale(
          x, y, w, h,
          target.w, target.h, d.cropScale,
        ),
      }
    })
    setCompare(false)
  }

  function toggleFlip(axis) {
    if (!img?.focal) {
      nudgeNeedFocal()
      return
    }
    const w = img.width || 0
    const h = img.height || 0
    setDraft((d) => {
      if (axis === 'h') {
        return { ...d, flipH: !d.flipH, x: (w - 1) - d.x }
      }
      return { ...d, flipV: !d.flipV, y: (h - 1) - d.y }
    })
    setCompare(false)
  }

  function nudgeZoom(deltaY) {
    if (!img?.focal) {
      nudgeNeedFocal()
      return
    }
    if (compare) return
    setDraft((d) => {
      const next = nudgeCropScale(d.cropScale, deltaY)
      return { ...d, cropScale: applyDraftScale(next, d.x, d.y) }
    })
    setCompare(false)
  }

  function onPointerDown(e) {
    if (!img?.focal) {
      if (e.button === 0 || e.button === 1) {
        e.preventDefault()
        nudgeNeedFocal()
      }
      return
    }
    if (compare) return
    if (e.button === 0) {
      e.preventDefault()
      drag.current = { mode: 'pan', x: e.clientX, y: e.clientY }
      e.currentTarget.setPointerCapture(e.pointerId)
    } else if (e.button === 1) {
      e.preventDefault()
      drag.current = { mode: 'zoom', y: e.clientY, scale: draft.cropScale }
      e.currentTarget.setPointerCapture(e.pointerId)
    }
  }

  function onPointerMove(e) {
    if (!drag.current) return
    if (drag.current.mode === 'pan') {
      const dx = e.clientX - drag.current.x
      const dy = e.clientY - drag.current.y
      drag.current = { ...drag.current, x: e.clientX, y: e.clientY }
      panBy(dx, dy)
    } else if (drag.current.mode === 'zoom') {
      const dy = e.clientY - drag.current.y
      const next = clampCropScale(drag.current.scale * (2 ** (dy / 180)))
      setDraft((d) => ({ ...d, cropScale: applyDraftScale(next, d.x, d.y) }))
      setCompare(false)
    }
  }

  function onPointerUp(e) {
    if (drag.current) {
      drag.current = null
      try { e.currentTarget.releasePointerCapture(e.pointerId) } catch { /* ignore */ }
    }
  }

  function onSourceLoad() {
    const token = loadGenRef.current
    const image = imgRef.current
    if (!image || token !== loadGenRef.current) return
    if (!sourceMatches() || !image.complete || !image.naturalWidth) return
    setSourceReady(true)
    drawLatest.current()
  }

  if (!img) return null

  function neighborMedia(other) {
    if (!other) return null
    const fh = other.flip_h ? 1 : 0
    const fv = other.flip_v ? 1 : 0
    return other.focal
      ? mediaUrl('preview', other.id, `?orientation=${session.alignment_mode || 'landscape'}&f=${other.focal[0]}-${other.focal[1]}&s=${other.crop_scale ?? 1}&n=${encodeURIComponent(other.filename)}&tw=${session.target_width}&th=${session.target_height}&fh=${fh}&fv=${fv}`)
      : mediaUrl('original', other.id, `?n=${encodeURIComponent(other.filename)}`)
  }

  const showPrev = neighbor < 0
  const showNext = neighbor > 0
  const neighborOpacity = Math.abs(neighbor)
  const neighborSrc = showPrev ? neighborMedia(prevImg) : showNext ? neighborMedia(nextImg) : null
  const neighborLabel = showPrev
    ? (prevImg ? `Prev ${Math.round(neighborOpacity * 100)}%` : 'No previous')
    : showNext
      ? (nextImg ? `Next ${Math.round(neighborOpacity * 100)}%` : 'No next')
      : 'Neighbors'

  const target = targetForMode(session)
  const zoomLabel = img.focal
    ? `${zoomFactor(
      view.x, view.y, img.width || 0, img.height || 0,
      target.w, target.h, view.cropScale,
    ).toFixed(2)}×`
    : '—'

  const prevDisabled = !prevImg || neighbor <= -1
  const nextDisabled = !nextImg || neighbor >= 1

  return (
    <div className="workspace preview">
      <div className="preview-toolbar">
        <div className="preview-toolbar-left">
          <button
            type="button"
            aria-selected={compare}
            disabled={Boolean(img.focal) && !dirty}
            title={
              !img.focal
                ? 'Set a focal on Original first'
                : dirty
                  ? 'Toggle saved vs draft framing (C)'
                  : 'Make a pan/zoom change to enable Compare'
            }
            onClick={() => {
              if (!img.focal) {
                nudgeNeedFocal()
                return
              }
              setCompare((v) => !v)
            }}
          >
            Compare (C)
          </button>
          <button
            type="button"
            disabled={Boolean(img.focal) && (!dirty || committing || compare)}
            title={!img.focal ? 'Set a focal on Original first' : undefined}
            onClick={() => {
              if (!img.focal) {
                nudgeNeedFocal()
                return
              }
              commit()
            }}
          >
            {committing ? 'Saving…' : 'Commit'}
          </button>
          <button
            type="button"
            className="secondary"
            aria-pressed={wrapNav}
            title={wrapNav ? 'Wrapping on: arrows loop the list' : 'Wrapping off: stop at first/last'}
            onClick={() => setWrapNav((v) => !v)}
          >
            Wrap {wrapNav ? 'On' : 'Off'}
          </button>
          <button
            type="button"
            className="secondary"
            aria-pressed={Boolean(view.flipH)}
            disabled={Boolean(img.focal) && compare}
            title={!img.focal ? 'Set a focal on Original first' : 'Flip horizontal'}
            onClick={() => toggleFlip('h')}
          >
            Flip H
          </button>
          <button
            type="button"
            className="secondary"
            aria-pressed={Boolean(view.flipV)}
            disabled={Boolean(img.focal) && compare}
            title={!img.focal ? 'Set a focal on Original first' : 'Flip vertical'}
            onClick={() => toggleFlip('v')}
          >
            Flip V
          </button>
        </div>
        <div className="preview-toolbar-center">
          <button
            type="button"
            className="secondary"
            disabled={prevDisabled}
            title="Previous neighbor (−10%)"
            onClick={() => stepNeighbor(-0.1)}
          >
            Prev
          </button>
          <span className="muted preview-opacity">{neighborLabel}</span>
          <button
            type="button"
            className="secondary"
            disabled={nextDisabled}
            title="Next neighbor (+10%)"
            onClick={() => stepNeighbor(0.1)}
          >
            Next
          </button>
        </div>
        <div className="preview-toolbar-right">
          <span className="muted">Zoom</span>
          <button
            type="button"
            className="secondary"
            disabled={!img.focal || compare}
            title="Zoom out"
            onClick={() => nudgeZoom(1)}
          >
            −
          </button>
          <span className={`muted${img.focal ? '' : ' preview-zoom-muted'}`}>{zoomLabel}</span>
          <button
            type="button"
            className="secondary"
            disabled={!img.focal || compare}
            title="Zoom in"
            onClick={() => nudgeZoom(-1)}
          >
            +
          </button>
        </div>
      </div>
      <div className="preview-viewport" ref={viewportRef}>
        <div
          className={`preview-frame ${img.focal && !compare ? 'interactive' : ''}${sourceReady ? '' : ' is-loading'}`}
          ref={stageRef}
          style={{ opacity: sourceReady ? 1 : 0 }}
        >
          <img
            ref={imgRef}
            className="preview-source"
            src={sourceSrc}
            alt=""
            draggable={false}
            onLoad={onSourceLoad}
          />
          <canvas
            ref={canvasRef}
            className="preview-base"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onContextMenu={(e) => e.preventDefault()}
          />
          {neighborSrc && neighborOpacity > 0 && (
            <img
              className="preview-neighbor"
              src={neighborSrc}
              alt=""
              draggable={false}
              style={{ opacity: neighborOpacity }}
            />
          )}
          {!img.focal && (
            <span
              key={focalPulse || 'idle'}
              className={`stage-note need-focal${focalPulse ? ' is-pulsing' : ''}`}
              role="status"
            >
              Set a focal on Original to fine-tune
            </span>
          )}
          {compare && <span className="stage-note">Compare: saved</span>}
        </div>
      </div>
    </div>
  )
}

export default function Aligner({ session, setSession, batchMode, onFinished }) {
  const [tab, setTab] = useState('original')
  const [pending, setPending] = useState(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportDone, setExportDone] = useState(false)
  const [resetOpen, setResetOpen] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [progress, setProgress] = useState(null)
  const [exportError, setExportError] = useState('')
  const [error, setError] = useState('')
  const [cols, setCols] = useColumnLayout()
  const [showGrid, setShowGrid] = useShowGrid()
  const [arrangeZoom, nudgeArrangeZoom] = useArrangeZoom()
  const [previewWrap, setPreviewWrap] = useState(() => {
    try { return localStorage.getItem(PREVIEW_WRAP_KEY) === '1' } catch { return false }
  })
  const [previewCompareReady, setPreviewCompareReady] = useState(false)
  const [previewCommitReady, setPreviewCommitReady] = useState(false)
  const previewCompareRef = useRef(null)
  const [maskImage, setMaskImage] = useState(null)
  const [showMask, setShowMask] = useState(false)
  const [maskInvert, setMaskInvert] = useState(false)
  const [maskHalfOpacity, setMaskHalfOpacity] = useState(true)
  const [maskFit, setMaskFit] = useState(() => {
    try {
      const v = localStorage.getItem(MASK_FIT_KEY)
      return v === 'cover' ? 'cover' : 'contain'
    } catch { return 'contain' }
  })
  const maskFileRef = useRef(null)
  const [arrangeView, setArrangeView] = useState('original')
  const [arrangeBusy, setArrangeBusy] = useState(false)
  const [arrangeStatus, setArrangeStatus] = useState('')
  const [arrangeProgress, setArrangeProgress] = useState(null) // { done, total, filename }
  const [leadHover, setLeadHover] = useState(false)
  const [arrangeSelected, setArrangeSelected] = useState(() => new Set())
  const arrangeAnchorRef = useRef(null)
  const [arrangeDragging, setArrangeDragging] = useState(null)
  const [compareA, setCompareA] = useState('original')
  const [compareB, setCompareB] = useState('1')
  const [compareShow, setCompareShow] = useState('a') // 'a' | 'b'
  const [arrangeMenuOpen, setArrangeMenuOpen, arrangeMenuRef] = useDismissableOpen(false)
  const workspaceRef = useRef(null)
  const colsRef = useRef(cols)
  const dragOrigin = useRef(cols)
  const discarding = useRef(false)
  const pendingRef = useRef(null)
  const previewDraftRef = useRef(null)
  colsRef.current = cols
  pendingRef.current = pending
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }))

  useEffect(() => {
    try { localStorage.setItem(MASK_FIT_KEY, maskFit) } catch { /* ignore */ }
  }, [maskFit])

  useEffect(() => {
    try { localStorage.setItem(PREVIEW_WRAP_KEY, previewWrap ? '1' : '0') } catch { /* ignore */ }
  }, [previewWrap])

  useEffect(() => {
    // Drop any pending tied to another image when selection changes.
    setPending((p) => (p && p.index != null && p.index !== session.current_idx ? null : p))
  }, [session.current_idx])

  useEffect(() => {
    const name = session.images[session.current_idx]?.filename
    if (!name) return
    setArrangeSelected((prev) => {
      if (prev.size <= 1) return new Set([name])
      if (prev.has(name)) return prev
      return new Set([name])
    })
  }, [session.current_idx])

  useEffect(() => {
    if (tab !== 'preview') {
      setPreviewCompareReady(false)
      setPreviewCommitReady(false)
      return undefined
    }
    const tick = () => {
      const api = previewCompareRef.current
      setPreviewCompareReady(Boolean(api?.canToggle))
      setPreviewCommitReady(Boolean(api?.canCommit))
    }
    tick()
    const id = window.setInterval(tick, 200)
    return () => window.clearInterval(id)
  }, [tab, session.current_idx])

  const ids = useMemo(() => session.images.map((im) => im.filename), [session])

  const apply = (next) => {
    setSession(next)
    setPending(null)
    pendingRef.current = null
    previewDraftRef.current = null
  }

  /** Persist pending Original / Preview crop changes for the current image before leaving it. */
  const flushPending = async () => {
    const p = pendingRef.current || previewDraftRef.current
    if (!p) return null
    const next = await api.setFocal({
      x: p.x,
      y: p.y,
      auto_center: Boolean(p.autoCenter),
      crop_scale: clampCropScale(p.cropScale ?? DEFAULT_CROP_SCALE),
      flip_h: p.flipH != null ? Boolean(p.flipH) : undefined,
      flip_v: p.flipV != null ? Boolean(p.flipV) : undefined,
      index: session.current_idx,
    })
    setPending(null)
    pendingRef.current = null
    previewDraftRef.current = null
    setSession(next)
    return next
  }

  const savePending = async () => flushPending()

  const switchTab = async (nextTab) => {
    if (nextTab === tab) return
    try {
      if (pendingRef.current || previewDraftRef.current) await flushPending()
      if (tab === 'arrange' && nextTab !== 'arrange') {
        const left = await api.arrangeLeave({ commit: true })
        setSession(left)
      }
      setTab(nextTab)
    } catch (err) {
      setError(err.message)
    }
  }

  const applyTarget = async (w, h) => {
    try {
      await flushPending()
      apply(await api.setTarget({ target_width: Number(w), target_height: Number(h) }))
    } catch (err) {
      setError(err.message)
    }
  }

  const runAutoArrange = async (mode, extra = {}) => {
    const busyMsg = {
      color: 'Sorting by color…',
      depth: extra.near_to_far === false ? 'Sorting depth far→near…' : 'Sorting depth near→far…',
      lead: 'Matching lead image…',
      faces: 'Sorting by faces…',
    }[mode] || 'Arranging…'
    setArrangeBusy(true)
    setArrangeStatus(busyMsg)
    setArrangeProgress({ done: 0, total: session.total || 1, filename: '' })
    setError('')
    try {
      const res = await api.arrangeAuto({ mode, ...extra })
      const next = await readSse(res, (ev) => {
        if (ev.phase === 'start' || ev.phase === 'progress') {
          setArrangeProgress({
            done: ev.done ?? 0,
            total: ev.total || session.total || 1,
            filename: ev.filename || '',
          })
          if (ev.filename && !String(ev.filename).endsWith('…')) {
            setArrangeStatus(`${busyMsg.replace(/…$/, '')} · ${ev.done}/${ev.total}`)
          } else if (ev.filename) {
            setArrangeStatus(String(ev.filename))
          }
        }
        if (ev.phase === 'error' || ev.error) {
          setError(ev.error || 'AutoArrange failed')
        }
      })
      if (!next || next.phase === 'error' || next.error) {
        throw new Error(next?.error || 'AutoArrange failed')
      }
      apply(next)
      const slot = next.auto_result?.slot
      const labels = next.auto_result?.labels
      const labelHint = Array.isArray(labels) && labels.length
        ? ` · ${labels.slice(0, 3).map((l) => (Array.isArray(l) ? l[0] : l)).join(', ')}${labels.length > 3 ? '…' : ''}`
        : ''
      setArrangeStatus(slot ? `Saved to slot ${slot}${labelHint}` : `Done${labelHint}`)
      setArrangeProgress(null)
      window.setTimeout(() => setArrangeStatus((s) => (s.startsWith('Saved') || s.startsWith('Done') ? '' : s)), 2800)
    } catch (err) {
      setError(err.message)
      setArrangeStatus('')
      setArrangeProgress(null)
    } finally {
      setArrangeBusy(false)
    }
  }

  const homeFocal = async () => {
    const im = session.images[session.current_idx]
    if (!im) return
    const pt = {
      x: im.width / 2,
      y: im.height / 2,
      autoCenter: true,
      cropScale: DEFAULT_CROP_SCALE,
      index: im.id,
    }
    setPending(pt)
  }

  const onMaskFile = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const url = URL.createObjectURL(file)
    const image = new Image()
    image.onload = () => {
      setMaskImage(image)
      setShowMask(true)
    }
    image.onerror = () => setError('Could not load mask image')
    image.src = url
    e.target.value = ''
  }

  const recallSlot = async (slot) => {
    try {
      apply(await api.arrangeRecall({ slot: String(slot) }))
    } catch (err) {
      setError(err.message)
    }
  }

  const reverseArrange = async () => {
    setError('')
    try {
      apply(await api.arrangeReverse())
    } catch (err) {
      setError(err.message)
    }
  }

  const toggleCompare = async () => {
    const slot = compareShow === 'a' ? compareB : compareA
    setCompareShow(compareShow === 'a' ? 'b' : 'a')
    await recallSlot(slot === '0' ? 'original' : slot)
  }

  const goTo = async (index, { wrap = false } = {}) => {
    if (index === session.current_idx) return
    await flushPending()
    apply(await api.navigate({ index, wrap }))
  }

  const step = async (direction) => {
    const wrap = tab === 'preview' && previewWrap
    if (!wrap) {
      const atStart = session.current_idx <= 0 && direction < 0
      const atEnd = session.current_idx >= session.total - 1 && direction > 0
      if (atStart || atEnd) return
    }
    await flushPending()
    apply(await api.navigate({ direction, wrap }))
  }

  const confirmPt = async (pt) => {
    await api.setFocal({
      x: pt.x,
      y: pt.y,
      auto_center: Boolean(pt.autoCenter),
      crop_scale: clampCropScale(pt.cropScale ?? DEFAULT_CROP_SCALE),
      index: session.current_idx,
    })
    apply(await api.confirm())
    return null
  }

  const commitPreview = async (pt) => {
    const next = await api.setFocal({
      x: pt.x,
      y: pt.y,
      auto_center: Boolean(pt.autoCenter),
      crop_scale: clampCropScale(pt.cropScale ?? DEFAULT_CROP_SCALE),
      flip_h: Boolean(pt.flipH),
      flip_v: Boolean(pt.flipV),
      index: session.current_idx,
    })
    setSession(next)
    setPending(null)
  }

  const discardCurrent = async () => {
    if (discarding.current) return
    discarding.current = true
    try {
      const next = await api.discard(session.current_idx)
      if (next.empty) onFinished()
      else apply(next)
    } finally {
      discarding.current = false
    }
  }

  const duplicateCurrent = async () => {
    try {
      await flushPending()
      apply(await api.duplicate())
    } catch (err) {
      setError(err.message)
    }
  }

  const onKey = useCallback(async (e) => {
    if (exportOpen) return
    if (resetOpen) {
      if (e.key === 'Escape') {
        e.preventDefault()
        if (!resetting) setResetOpen(false)
      }
      return
    }
    if (e.target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return
    const k = e.key
    if (!hotkeyAllowed(tab, k)) return
    try {
      if (k === 'Enter') {
        if (tab === 'preview') {
          e.preventDefault()
          const api = previewCompareRef.current
          if (!session.images[session.current_idx]?.focal) api?.nudgeNeedFocal?.()
          else api?.commit?.()
          return
        }
        const img = session.images[session.current_idx]
        await confirmPt(focalFromImage(img, pending))
      } else if (k === ' ') {
        e.preventDefault()
        await step(1)
      } else if (k === 'ArrowRight') {
        e.preventDefault()
        await step(1)
      } else if (k === 'ArrowLeft') {
        e.preventDefault()
        await step(-1)
      } else if (k === 'x' || k === 'X') await discardCurrent()
      else if (k === 'd' || k === 'D') {
        e.preventDefault()
        await duplicateCurrent()
      } else if (k === 'Delete' || k === 'Backspace') apply(await api.clearFocal(session.current_idx))
      else if (k === 'p' || k === 'P') await switchTab(tab === 'preview' ? 'original' : 'preview')
      else if (k === 'o' || k === 'O') {
        const mode = session.alignment_mode === 'portrait' ? 'landscape' : 'portrait'
        apply(await api.setMode(mode))
      } else if (k === 'a' || k === 'A') await switchTab(tab === 'arrange' ? 'original' : 'arrange')
      else if (k === 'h' || k === 'H') {
        e.preventDefault()
        await homeFocal()
      } else if (k === 'r' || k === 'R') setResetOpen(true)
      else if (k === 'g' || k === 'G') {
        e.preventDefault()
        setShowGrid((v) => !v)
      } else if (k === 'i' || k === 'I') {
        e.preventDefault()
        if (maskImage) setShowMask((v) => !v)
      }       else if (k === 'e' || k === 'E') setExportOpen(true)
      else if (k === 'c' || k === 'C') {
        e.preventDefault()
        if (tab === 'arrange') await toggleCompare()
        else if (tab === 'preview') {
          const api = previewCompareRef.current
          if (!session.images[session.current_idx]?.focal) api?.nudgeNeedFocal?.()
          else api?.toggle?.()
        }
      } else if (/^[0-9]$/.test(k)) {
        e.preventDefault()
        await recallSlot(k === '0' ? 'original' : k)
      } else if (k === 'Escape') onFinished()
    } catch (err) {
      setError(err.message)
    }
  }, [session, pending, tab, exportOpen, resetOpen, resetting, onFinished, setShowGrid, compareA, compareB, compareShow, maskImage, previewWrap])

  useEffect(() => {
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onKey])

  async function confirmReset() {
    if (resetting) return
    setResetting(true)
    setError('')
    try {
      apply(await api.reset())
      setResetOpen(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setResetting(false)
    }
  }

  const img = session.images[session.current_idx]
  const prev = session.images[session.current_idx - 1]
  const nextImg = session.images[session.current_idx + 1]
  const focalPct = session.total ? (100 * session.completed_count) / session.total : 0

  function dragSplit(side, dx) {
    const width = workspaceRef.current?.clientWidth || 1
    const dPct = (dx / width) * 100
    const [l, c, r] = dragOrigin.current
    let next
    if (side === 'left') {
      const left = Math.min(40, Math.max(8, l + dPct))
      next = [left, Math.max(30, c - (left - l)), r]
    } else {
      const right = Math.min(40, Math.max(8, r - dPct))
      next = [l, Math.max(30, c - (right - r)), right]
    }
    const sum = next[0] + next[1] + next[2]
    setCols(next.map((n) => (n / sum) * 100))
  }

  async function onDragStart(event) {
    const id = event.active.id
    setArrangeDragging(id)
    setArrangeSelected((prev) => {
      if (prev.has(id)) return prev
      arrangeAnchorRef.current = id
      return new Set([id])
    })
  }

  async function onDragEnd(event) {
    const { active, over } = event
    setArrangeDragging(null)
    if (!over || active.id === over.id) return
    const names = session.images.map((im) => im.filename)
    const selected = arrangeSelected.has(active.id)
      ? arrangeSelected
      : new Set([active.id])
    const nextNames = reorderMulti(names, selected, active.id, over.id)
    if (nextNames.every((n, i) => n === names[i])) return
    const nameToOldIndex = Object.fromEntries(names.map((n, i) => [n, i]))
    const order = nextNames.map((n) => nameToOldIndex[n])
    const currentName = session.images[session.current_idx]?.filename
    const optimistic = nextNames.map((n) => session.images[nameToOldIndex[n]]).map((im, i) => ({ ...im, id: i }))
    const newCurrent = Math.max(0, optimistic.findIndex((im) => im.filename === currentName))
    setSession({ ...session, images: optimistic, current_idx: newCurrent })
    setArrangeSelected(new Set(selected))
    try {
      apply(await api.order(order))
    } catch (err) {
      setError(err.message)
      apply(await api.session())
    }
  }

  async function onArrangeSelect(e, id, filename) {
    const names = session.images.map((im) => im.filename)
    const idx = names.indexOf(filename)
    if (e.metaKey || e.ctrlKey) {
      setArrangeSelected((prev) => {
        const next = new Set(prev)
        if (next.has(filename)) {
          if (next.size > 1) next.delete(filename)
        } else {
          next.add(filename)
        }
        return next
      })
      arrangeAnchorRef.current = filename
    } else if (e.shiftKey) {
      const anchor = arrangeAnchorRef.current || session.images[session.current_idx]?.filename
      const a = names.indexOf(anchor)
      const from = Math.min(a < 0 ? idx : a, idx)
      const to = Math.max(a < 0 ? idx : a, idx)
      setArrangeSelected(new Set(names.slice(from, to + 1)))
    } else {
      setArrangeSelected(new Set([filename]))
      arrangeAnchorRef.current = filename
    }
    try {
      await flushPending()
      apply(await api.navigate({ index: id }))
    } catch (err) {
      setError(err.message)
    }
  }

  async function runExport(orientation) {
    setExporting(true)
    setExportDone(false)
    setExportError('')
    setError('')
    setProgress({ done: 0, total: session.total, phase: 'start' })
    try {
      const res = await api.export({
        output_folder: session.output_folder,
        orientation,
        cleanup: true,
      })
      const last = await readSse(res, (ev) => {
        setProgress(ev)
        if (ev.phase === 'error' || ev.error) {
          setExportError(ev.error || 'Export failed')
        }
      })
      if (!last || last.phase === 'error' || last.error) {
        throw new Error(last?.error || exportError || 'Export failed')
      }
      setProgress(last)
      setExportDone(true)
    } catch (e) {
      setExportError(e.message)
      setError(e.message)
    } finally {
      setExporting(false)
    }
  }

  function finishAfterExport() {
    setExportOpen(false)
    setExportDone(false)
    setProgress(null)
    setExportError('')
    onFinished()
  }

  return (
    <div className="screen">
      <div className="header-bar">
        <div className="header-meta">
          <h2>{img?.filename}</h2>
          <div className="status">
            {session.current_idx + 1}/{session.total} · {session.alignment_mode}
            {' · '}{session.target_width}×{session.target_height}
          </div>
          <div className="focal-progress" title={`${session.completed_count} of ${session.total} have a focal point`}>
            <div className="focal-progress-bar"><div style={{ width: `${focalPct}%` }} /></div>
            <span>{session.completed_count}/{session.total} focals</span>
          </div>
        </div>
        <div className="tabs">
          <button aria-selected={tab === 'original'} onClick={() => switchTab('original')}>Original</button>
          <button aria-selected={tab === 'preview'} onClick={() => switchTab('preview')}>Preview</button>
          <button aria-selected={tab === 'arrange'} onClick={() => switchTab('arrange')}>Arrange</button>
        </div>
        <div className="row header-actions">
          {tab === 'original' && (
            <button
              type="button"
              className="secondary"
              title="Duplicate current image after this one (D)"
              onClick={() => duplicateCurrent().catch((err) => setError(err.message))}
            >
              Duplicate (D)
            </button>
          )}
          <button className="secondary" disabled={exporting} onClick={() => { setExportOpen(true); setExportDone(false); setProgress(null); setExportError('') }}>Export</button>
          <button className="secondary" onClick={onFinished}>Done</button>
        </div>
      </div>

      <div className="action-bar">
        <SizePanel
          width={session.target_width}
          height={session.target_height}
          onApply={applyTarget}
        />
        <OverlayPanel
          showGrid={showGrid}
          setShowGrid={setShowGrid}
          maskImage={maskImage}
          showMask={showMask}
          setShowMask={setShowMask}
          maskInvert={maskInvert}
          setMaskInvert={setMaskInvert}
          maskHalfOpacity={maskHalfOpacity}
          setMaskHalfOpacity={setMaskHalfOpacity}
          maskFit={maskFit}
          setMaskFit={setMaskFit}
          onPickMask={() => maskFileRef.current?.click()}
        />
        <input
          ref={maskFileRef}
          type="file"
          accept="image/*"
          hidden
          onChange={onMaskFile}
        />
        <ImageFacts img={img} pending={pending} />
      </div>

      {tab === 'original' && (
        <div className="original-workspace-wrap">
          <div
            className="workspace"
            ref={workspaceRef}
            style={{ gridTemplateColumns: `${cols[0]}% 6px ${cols[1]}% 6px ${cols[2]}%` }}
          >
            <SidePane img={prev} label="Previous" onOpen={() => goTo(session.current_idx - 1)} />
            <SplitHandle onBegin={() => { dragOrigin.current = colsRef.current }} onDrag={(dx) => dragSplit('left', dx)} />
            <FocalStage
              session={session}
              pending={pending}
              setPending={setPending}
              onConfirm={confirmPt}
              onDiscard={() => discardCurrent().catch((err) => setError(err.message))}
              showGrid={showGrid}
              maskImage={maskImage}
              showMask={showMask}
              maskInvert={maskInvert}
              maskHalfOpacity={maskHalfOpacity}
              maskFit={maskFit}
            />
            <SplitHandle onBegin={() => { dragOrigin.current = colsRef.current }} onDrag={(dx) => dragSplit('right', dx)} />
            <SidePane img={nextImg} label="Next" onOpen={() => goTo(session.current_idx + 1)} />
          </div>
          {img?.media_kind === 'video' && (
            <VideoScrubber
              img={img}
              onSession={(next) => setSession(next)}
              onLocalWork={(wf) => {
                setSession((s) => ({
                  ...s,
                  images: s.images.map((im) => (
                    im.id === img.id ? { ...im, work_frame: wf } : im
                  )),
                }))
              }}
              onError={(msg) => setError(msg)}
            />
          )}
        </div>
      )}

      {tab === 'preview' && img && (
        <PreviewStage
          session={session}
          onCommit={commitPreview}
          onError={(msg) => setError(msg)}
          showGrid={showGrid}
          draftFlushRef={previewDraftRef}
          maskImage={maskImage}
          showMask={showMask}
          maskInvert={maskInvert}
          maskHalfOpacity={maskHalfOpacity}
          maskFit={maskFit}
          wrapNav={previewWrap}
          setWrapNav={setPreviewWrap}
          compareApiRef={previewCompareRef}
        />
      )}

      {tab === 'arrange' && (
        <div className="workspace arrange">
          <div className="arrange-toolbar">
            <div className="arrange-toolbar-row">
              <div className="arrange-toolbar-left">
                <button type="button" aria-selected={arrangeView === 'original'} onClick={() => setArrangeView('original')}>Original</button>
                <button type="button" aria-selected={arrangeView === 'aligned'} onClick={() => setArrangeView('aligned')}>Aligned</button>
                <label className="muted arrange-compare">
                  Compare
                  <select value={compareA} onChange={(e) => setCompareA(e.target.value)}>
                    {['original', '1', '2', '3', '4', '5', '6', '7', '8', '9'].map((s) => (
                      <option key={`a-${s}`} value={s}>{s === 'original' ? 'Original' : s}</option>
                    ))}
                  </select>
                  vs
                  <select value={compareB} onChange={(e) => setCompareB(e.target.value)}>
                    {['original', '1', '2', '3', '4', '5', '6', '7', '8', '9'].map((s) => (
                      <option key={`b-${s}`} value={s}>{s === 'original' ? 'Original' : s}</option>
                    ))}
                  </select>
                </label>
                <button type="button" className="secondary" onClick={toggleCompare}>
                  Show {compareShow === 'a' ? compareB : compareA} (C)
                </button>
              </div>
              <div className="arrange-toolbar-center">
                <div className="image-facts arrange-menu" ref={arrangeMenuRef}>
                  {(arrangeBusy || arrangeStatus) && (
                    <div className={`arrange-progress-float${arrangeBusy ? ' busy' : ' done'}`} role="status">
                      <div className="arrange-progress-label">
                        {arrangeBusy ? (arrangeStatus || 'Working…') : arrangeStatus}
                      </div>
                      {arrangeBusy && arrangeProgress && (
                        <div className="arrange-progress-track">
                          <div
                            className="arrange-progress-bar"
                            style={{
                              width: `${Math.min(100, (100 * (arrangeProgress.done || 0)) / Math.max(1, arrangeProgress.total || 1))}%`,
                            }}
                          />
                        </div>
                      )}
                      {arrangeBusy && arrangeProgress && (
                        <div className="arrange-progress-meta muted">
                          {arrangeProgress.done}/{arrangeProgress.total}
                          {arrangeProgress.filename && !String(arrangeProgress.filename).endsWith('…')
                            ? ` · ${arrangeProgress.filename}`
                            : arrangeProgress.filename
                              ? ` · ${arrangeProgress.filename}`
                              : ''}
                        </div>
                      )}
                    </div>
                  )}
                  <button
                    type="button"
                    className="facts-toggle"
                    onClick={() => setArrangeMenuOpen((v) => !v)}
                    aria-expanded={arrangeMenuOpen}
                    title="AutoArrange, slots, and info"
                  >
                    <span className="facts-role">Arrange</span>
                    <span className="facts-caret" aria-hidden="true">{arrangeMenuOpen ? '▴' : '▾'}</span>
                  </button>
                  {arrangeMenuOpen && (
                    <div className="facts-panel arrange-menu-panel">
                      <div className="arrange-menu-actions">
                        <button type="button" className="secondary" disabled={arrangeBusy} onClick={() => runAutoArrange('color')}>Color</button>
                        <button type="button" className="secondary" disabled={arrangeBusy} onClick={() => runAutoArrange('depth', { near_to_far: true })}>Depth near→far</button>
                        <button
                          type="button"
                          className="secondary"
                          disabled={arrangeBusy}
                          title="Uses the selected thumbnail as the ORB lead — hover to highlight it"
                          onMouseEnter={() => setLeadHover(true)}
                          onMouseLeave={() => setLeadHover(false)}
                          onFocus={() => setLeadHover(true)}
                          onBlur={() => setLeadHover(false)}
                          onClick={() => runAutoArrange('lead', { lead_index: session.current_idx, axis: 'x' })}
                        >
                          Lead match
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          disabled={arrangeBusy}
                          title="Sorts left→right by largest detected face center"
                          onClick={() => runAutoArrange('faces')}
                        >
                          Faces
                        </button>
                        <button
                          type="button"
                          className={session.arrangement_reversed ? '' : 'secondary'}
                          aria-selected={Boolean(session.arrangement_reversed)}
                          disabled={arrangeBusy || session.total < 2}
                          title={session.arrangement_reversed ? 'Order is reversed — click to restore' : 'Reverse current order in place (updates active slot)'}
                          onClick={() => reverseArrange()}
                        >
                          Reverse
                        </button>
                      </div>
                      <div className="panel-section-label">Slots</div>
                      <div className="arrange-menu-slots">
                        {['original', '1', '2', '3', '4', '5', '6', '7', '8', '9'].map((slot) => {
                          const filled = slot === 'original' || Boolean(session.arrangements?.[slot])
                          const active = (session.arrangement_active || 'original') === slot
                          return (
                            <button
                              key={slot}
                              type="button"
                              className={active ? '' : 'secondary'}
                              disabled={!filled}
                              title={slot === 'original' ? 'Original (0)' : `Slot ${slot}`}
                              onClick={() => recallSlot(slot)}
                            >
                              {slot === 'original' ? 'Orig' : slot}
                            </button>
                          )
                        })}
                      </div>
                      <div className="arrange-menu-info" role="note">
                        <p><strong>Color</strong> — groups by HSV buckets (white / gray / black / hue).</p>
                        <p><strong>Depth near→far</strong> — Depth-Anything estimate; use Reverse for far→near.</p>
                        <p><strong>Lead match</strong> — ORB feature match against the selected thumbnail (hover Lead to see which).</p>
                        <p><strong>Faces</strong> — left→right by detected face centers (YuNet).</p>
                        <p><strong>Reverse</strong> — flips the active slot’s order in place (button stays lit while reversed).</p>
                        <p><strong>Slots 0–9</strong> — store and recall arrangements; leaving Arrange commits a manual draft.</p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
              <div className="arrange-toolbar-right">
                <span className="muted">Zoom</span>
                <button type="button" className="secondary" onClick={() => nudgeArrangeZoom(-0.1)} title="Smaller thumbs">−</button>
                <span className="muted">{Math.round(arrangeZoom * 100)}%</span>
                <button type="button" className="secondary" onClick={() => nudgeArrangeZoom(0.1)} title="Larger thumbs">+</button>
              </div>
            </div>
          </div>
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            onDragCancel={() => setArrangeDragging(null)}
          >
            <SortableContext items={ids} strategy={rectSortingStrategy}>
              <div className={`grid${leadHover ? ' lead-hover' : ''}`} style={{ '--arrange-zoom': arrangeZoom }}>
                {session.images.map((im) => (
                  <SortableThumb
                    key={im.filename}
                    id={im.filename}
                    img={im}
                    view={arrangeView}
                    orientation={session.alignment_mode}
                    targetW={session.target_width}
                    targetH={session.target_height}
                    selected={arrangeSelected.has(im.filename)}
                    current={im.id === session.current_idx}
                    multiCount={arrangeDragging === im.filename ? arrangeSelected.size : 0}
                    onSelect={onArrangeSelect}
                    onOpen={async (id) => {
                      try {
                        await flushPending()
                        apply(await api.navigate({ index: id }))
                        setTab('original')
                      } catch (err) {
                        setError(err.message)
                      }
                    }}
                    onDiscard={async (id) => {
                      try {
                        await flushPending()
                        const next = await api.discard(id)
                        if (next.empty) onFinished()
                        else apply(next)
                      } catch (err) {
                        setError(err.message)
                      }
                    }}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <NavDots session={session} onGo={async (idx) => { try { await goTo(idx) } catch (err) { setError(err.message) } }} />

      <div className="hotkeys">
        <Hotkey kbd="← →" label="Navigate" onClick={() => step(1)} />
        {tab === 'original' && (
          <>
            <Hotkey kbd="Enter" label="Save" onClick={async () => { try { await confirmPt(focalFromImage(img, pending)) } catch (err) { setError(err.message) } }} />
            <Hotkey kbd="Space" label="Skip" onClick={() => step(1)} />
            <Hotkey kbd="D" label="Duplicate" onClick={() => duplicateCurrent().catch((err) => setError(err.message))} />
          </>
        )}
        <Hotkey kbd="X / ⇧MMB" label="Discard" danger onClick={() => discardCurrent().catch((err) => setError(err.message))} />
        {tab === 'original' && (
          <Hotkey kbd="Del" label="Clear" onClick={async () => { try { apply(await api.clearFocal(session.current_idx)) } catch (err) { setError(err.message) } }} />
        )}
        <Hotkey kbd="P" label="Preview" onClick={() => switchTab(tab === 'preview' ? 'original' : 'preview')} />
        <Hotkey kbd="O" label="Orient" onClick={async () => { try { apply(await api.setMode(session.alignment_mode === 'portrait' ? 'landscape' : 'portrait')) } catch (err) { setError(err.message) } }} />
        <Hotkey kbd="A" label="Arrange" onClick={() => switchTab(tab === 'arrange' ? 'original' : 'arrange')} />
        {tab === 'original' && (
          <>
            <Hotkey kbd="H" label="Home" onClick={() => homeFocal().catch((err) => setError(err.message))} />
            <Hotkey kbd="G" label="Grid" onClick={() => setShowGrid((v) => !v)} />
            <Hotkey
              kbd="I"
              label="Mask"
              onClick={() => { if (maskImage) setShowMask((v) => !v) }}
            />
          </>
        )}
        {tab === 'preview' && (
          <>
            <Hotkey
              kbd="Enter"
              label="Commit"
              disabled={!previewCommitReady && Boolean(img?.focal)}
              onClick={() => {
                if (!img?.focal) previewCompareRef.current?.nudgeNeedFocal?.()
                else previewCompareRef.current?.commit?.()
              }}
            />
            <Hotkey
              kbd="C"
              label="Compare"
              disabled={!previewCompareReady && Boolean(img?.focal)}
              onClick={() => {
                if (!img?.focal) previewCompareRef.current?.nudgeNeedFocal?.()
                else previewCompareRef.current?.toggle?.()
              }}
            />
            <Hotkey
              kbd="<"
              label="Prev neighbor"
              onClick={() => previewCompareRef.current?.stepNeighbor?.(-0.1)}
            />
            <Hotkey
              kbd=">"
              label="Next neighbor"
              onClick={() => previewCompareRef.current?.stepNeighbor?.(0.1)}
            />
          </>
        )}
        {tab === 'arrange' && (
          <Hotkey kbd="C" label="Compare" onClick={() => toggleCompare().catch((err) => setError(err.message))} />
        )}
        <Hotkey kbd="R" label="Reset" danger onClick={() => setResetOpen(true)} />
        <Hotkey kbd="E" label="Export" onClick={() => setExportOpen(true)} />
        <Hotkey kbd="Esc" label={batchMode ? 'Next folder' : 'Opener'} onClick={onFinished} />
      </div>

      {resetOpen && (
        <div className="export-overlay" onClick={() => !resetting && setResetOpen(false)}>
          <div className="export-card card" onClick={(e) => e.stopPropagation()}>
            <h2>Reset all focals?</h2>
            <p className="muted">
              Clears every focal point and crop scale in this session ({session.completed_count} set).
              Preview cache is removed. This cannot be undone.
            </p>
            <div className="row" style={{ marginTop: 16 }}>
              <button className="danger" disabled={resetting} onClick={confirmReset}>
                {resetting ? 'Resetting…' : 'Reset all'}
              </button>
              <button className="secondary" disabled={resetting} onClick={() => setResetOpen(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {exportOpen && (
        <div className="export-overlay" onClick={() => !exporting && !exportDone && setExportOpen(false)}>
          <div className="export-card card" onClick={(e) => e.stopPropagation()}>
            <h2>{exportDone ? 'Export complete' : exporting ? 'Exporting…' : 'Export aligned images'}</h2>
            <p className="muted">
              {session.completed_count}/{session.total} have focals → {session.output_folder}
            </p>
            {!exportDone && (
              <div className="row" style={{ marginTop: 16 }}>
                <button disabled={exporting} onClick={() => runExport('landscape')}>Landscape</button>
                <button disabled={exporting} className="secondary" onClick={() => runExport('portrait')}>Portrait</button>
              </div>
            )}
            {(exporting || progress) && (
              <div style={{ marginTop: 16 }}>
                <div className="progress">
                  <div style={{ width: `${(100 * (progress?.done || 0)) / (progress?.total || session.total || 1)}%` }} />
                </div>
                <p className="muted" style={{ marginTop: 8 }}>
                  {exportDone
                    ? `${progress?.exported ?? progress?.done ?? 0} of ${progress?.total ?? session.total} written`
                    : exporting
                      ? `${progress?.done || 0}/${progress?.total || session.total}${progress?.filename ? ` · ${progress.filename}` : ''}`
                      : null}
                </p>
                {exportDone && progress?.output_folder && (
                  <p className="ok" style={{ marginTop: 8 }}>Saved to {progress.output_folder}</p>
                )}
              </div>
            )}
            {exportError && <p className="error" style={{ marginTop: 12 }}>{exportError}</p>}
            {exportDone && (
              <div className="row" style={{ marginTop: 16 }}>
                <button onClick={finishAfterExport}>{batchMode ? 'Next folder' : 'Back to opener'}</button>
                <button className="secondary" onClick={() => { setExportOpen(false); setExportDone(false); setProgress(null) }}>Stay</button>
              </div>
            )}
            {!exportDone && !exporting && (
              <div className="row" style={{ marginTop: 12 }}>
                <button className="secondary" onClick={() => setExportOpen(false)}>Cancel</button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
