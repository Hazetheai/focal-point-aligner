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
  drawRuleOfThirds,
  drawCompositionMask,
  interpolateFromKeyframes,
  KEYFRAME_EASES,
  DEFAULT_KEYFRAME_EASE,
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
const HOTKEYS_PREVIEW = new Set(['c', 'C', 'Enter', '<', '>', ',', '.', ' '])
/** Extra keys on Arrange. */
const HOTKEYS_ARRANGE = new Set(['0', '1', '2', '3', '4', '5', '6', 'Backspace', 'Delete'])
const ARRANGEMENT_SLOTS = ['original', '1', '2', '3', '4', '5', '6']
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
  const pendingMatches = pending && (pending.index == null || pending.index === img?.id)

  // Videos: never let a stale pending from another keyframe win over the playhead KF.
  if (img?.media_kind === 'video' && Array.isArray(img.keyframes) && img.keyframes.length) {
    const wf = Number(img.work_frame ?? 0)
    const pendingForWork = pendingMatches
      && pending.keyframeFrame != null
      && Number(pending.keyframeFrame) === wf
    if (pendingForWork) return pending

    const exact = img.keyframes.find((k) => Number(k.frame) === wf)
    if (exact) {
      return {
        x: Number(exact.focal_x),
        y: Number(exact.focal_y),
        autoCenter: false,
        cropScale: clampCropScale(exact.crop_scale ?? img.crop_scale ?? DEFAULT_CROP_SCALE),
        keyframeFrame: wf,
      }
    }
    // Between keyframes: keep an in-progress edit for this work frame, else interpolate.
    if (pendingMatches && (pending.keyframeFrame == null || Number(pending.keyframeFrame) === wf)) {
      return pending
    }
    const interp = interpolateFromKeyframes(img.keyframes, wf)
    if (interp) {
      return {
        x: interp.x,
        y: interp.y,
        autoCenter: false,
        cropScale: clampCropScale(interp.cropScale),
        keyframeFrame: wf,
      }
    }
  }

  if (pendingMatches) return pending
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
      {img.media_kind === 'video' && (
        <span className="thumb-video-badge" title="Video" aria-label="Video">▶</span>
      )}
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

function IconSun() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <circle cx="8" cy="8" r="2.6" fill="none" stroke="currentColor" strokeWidth="1.35" />
      <path d="M8 1.8v1.6M8 12.6v1.6M1.8 8h1.6M12.6 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M12.6 3.4l-1.1 1.1M4.5 11.5l-1.1 1.1" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}

function IconMoon() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M12.8 9.6A5.2 5.2 0 0 1 6.4 3.2 5.4 5.4 0 1 0 12.8 9.6z" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinejoin="round" />
    </svg>
  )
}

function IconInfo() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <circle cx="8" cy="8" r="5.4" fill="none" stroke="currentColor" strokeWidth="1.35" />
      <path d="M8 7.2v4.2M8 4.6v.2" fill="none" stroke="currentColor" strokeWidth="1.45" strokeLinecap="round" />
    </svg>
  )
}

function IconPlay() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M4.5 2.8v10.4L13.2 8z" fill="currentColor" />
    </svg>
  )
}

function IconPause() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <rect x="3.5" y="2.5" width="3.2" height="11" rx="0.6" fill="currentColor" />
      <rect x="9.3" y="2.5" width="3.2" height="11" rx="0.6" fill="currentColor" />
    </svg>
  )
}

function IconWrap() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path
        d="M3.5 5.5h7.2a2.8 2.8 0 0 1 0 5.6H6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <path d="M5.2 8.8 3.2 11l2 2.1" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <path
        d="M12.5 10.5H5.3a2.8 2.8 0 0 1 0-5.6H10"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        opacity="0.35"
      />
    </svg>
  )
}

/** Flip over the X axis (upside down). */
function IconFlipX() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <rect x="4" y="1.5" width="8" height="4.5" rx="0.7" fill="currentColor" opacity="0.35" />
      <rect x="4" y="10" width="8" height="4.5" rx="0.7" fill="none" stroke="currentColor" strokeWidth="1.25" />
      <line x1="2" y1="8" x2="14" y2="8" stroke="currentColor" strokeWidth="1.1" strokeDasharray="2 1.5" />
      <path d="M8 6.2v3.6M6.4 8.2 8 9.8l1.6-1.6" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** Flip over the Y axis (left ↔ right). */
function IconFlipY() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <rect x="1.5" y="4" width="4.5" height="8" rx="0.7" fill="currentColor" opacity="0.35" />
      <rect x="10" y="4" width="4.5" height="8" rx="0.7" fill="none" stroke="currentColor" strokeWidth="1.25" />
      <line x1="8" y1="2" x2="8" y2="14" stroke="currentColor" strokeWidth="1.1" strokeDasharray="2 1.5" />
      <path d="M6.2 8h3.6M7.8 6.4 9.4 8l-1.6 1.6" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconCommit() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M3.2 8.2 6.4 11.4 12.8 4.6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconChevronLeft() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M10.2 3.2 5.4 8l4.8 4.8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconChevronRight() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M5.8 3.2 10.6 8 5.8 12.8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconZoomOut() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <circle cx="7" cy="7" r="4.4" fill="none" stroke="currentColor" strokeWidth="1.35" />
      <path d="M10.2 10.2 13.5 13.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M4.8 7h4.4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}

function IconZoomIn() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <circle cx="7" cy="7" r="4.4" fill="none" stroke="currentColor" strokeWidth="1.35" />
      <path d="M10.2 10.2 13.5 13.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M4.8 7h4.4M7 4.8v4.4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}

function IconDuplicate() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path d="M10.5 5.5V3.8A1.3 1.3 0 0 0 9.2 2.5H3.8A1.3 1.3 0 0 0 2.5 3.8v5.4A1.3 1.3 0 0 0 3.8 10.5H5.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  )
}

function IconExport() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M8 2.5v7.2" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M5.2 5.2 8 2.5l2.8 2.7" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3 10.5v1.7A1.3 1.3 0 0 0 4.3 13.5h7.4A1.3 1.3 0 0 0 13 12.2v-1.7" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" />
    </svg>
  )
}

function IconDone() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M2.8 3.2h5.4A1.4 1.4 0 0 1 9.6 4.6v6.8A1.4 1.4 0 0 1 8.2 12.8H2.8" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      <path d="M7 8h6.2M11.2 5.6 13.6 8l-2.4 2.4" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconViewOriginal() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <rect x="2" y="3" width="12" height="10" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="5.5" cy="6.2" r="1.1" fill="currentColor" />
      <path d="M2.8 11.2 6.2 8.2l2.2 2 2.2-2.6 2.6 3.6" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  )
}

function IconViewAligned() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <rect x="1.5" y="2.5" width="13" height="11" rx="1" fill="none" stroke="currentColor" strokeWidth="1.15" opacity="0.35" />
      <rect x="4" y="3.5" width="8" height="9" rx="0.8" fill="none" stroke="currentColor" strokeWidth="1.35" />
      <circle cx="6.2" cy="6.2" r="0.9" fill="currentColor" />
      <path d="M4.4 11.2 6.8 8.8l1.6 1.5 1.5-1.8 1.7 2.7" fill="none" stroke="currentColor" strokeWidth="1.15" strokeLinejoin="round" />
    </svg>
  )
}

function IconSwap() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M3 5.5h8.5" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" />
      <path d="M9.5 3.2 12.2 5.5 9.5 7.8" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M13 10.5H4.5" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" />
      <path d="M6.5 8.2 3.8 10.5 6.5 12.8" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** Peek / show the other compare slot. */
function IconShowSlot() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M1.8 8c1.6-3 3.8-4.5 6.2-4.5S12.6 5 14.2 8c-1.6 3-3.8 4.5-6.2 4.5S3.4 11 1.8 8z" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="8" cy="8" r="2.1" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="8" cy="8" r="0.7" fill="currentColor" />
    </svg>
  )
}

function IconOverlayPrev() {
  return (
    <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true">
      <rect x="6.5" y="3.5" width="11" height="12.5" rx="1.2" fill="currentColor" opacity="0.28" />
      <rect x="2.5" y="5" width="11" height="12.5" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M9.2 9.2 6.4 12l2.8 2.8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconOverlayClear() {
  return (
    <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true">
      <rect x="4" y="3.5" width="12" height="13" rx="1.3" fill="none" stroke="currentColor" strokeWidth="1.45" />
      <path d="M7.2 7.2 12.8 12.8M12.8 7.2 7.2 12.8" fill="none" stroke="currentColor" strokeWidth="1.45" strokeLinecap="round" />
    </svg>
  )
}

function IconOverlayNext() {
  return (
    <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true">
      <rect x="2.5" y="3.5" width="11" height="12.5" rx="1.2" fill="currentColor" opacity="0.28" />
      <rect x="6.5" y="5" width="11" height="12.5" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M10.8 9.2 13.6 12l-2.8 2.8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconArrangeColor() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <circle cx="5.2" cy="5.5" r="2.4" fill="currentColor" opacity="0.55" />
      <circle cx="10.5" cy="5.2" r="2.4" fill="currentColor" opacity="0.35" />
      <circle cx="8" cy="10.5" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  )
}

function IconArrangeDepth() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M2 11.5 5.5 6.2 8 9.2l2.2-2.8L14 11.5z" fill="currentColor" opacity="0.3" />
      <path d="M2 11.5 5.5 6.2 8 9.2l2.2-2.8L14 11.5" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round" />
      <path d="M2.5 13h11" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )
}

function IconArrangeLead() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <circle cx="8" cy="8" r="4.4" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="8" cy="8" r="1.3" fill="currentColor" />
      <path d="M8 2.2v2.1M8 11.7v2.1M2.2 8h2.1M11.7 8h2.1" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  )
}

function IconArrangeFaces() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <circle cx="8" cy="5.5" r="2.4" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path d="M3.5 13.2c.6-2.6 2.4-3.9 4.5-3.9s3.9 1.3 4.5 3.9" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}

function IconArrangeManual() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M3 4.5h10M3 8h10M3 11.5h7" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" />
      <circle cx="12.2" cy="11.5" r="1.3" fill="currentColor" />
    </svg>
  )
}

function arrangeMethodIcon(method) {
  switch (method) {
    case 'color': return <IconArrangeColor />
    case 'depth': return <IconArrangeDepth />
    case 'lead': return <IconArrangeLead />
    case 'faces': return <IconArrangeFaces />
    case 'manual': return <IconArrangeManual />
    default: return null
  }
}

function arrangeMethodLabel(method) {
  switch (method) {
    case 'color': return 'Color'
    case 'depth': return 'Depth'
    case 'lead': return 'Lead match'
    case 'faces': return 'Faces'
    case 'manual': return 'Manual'
    default: return null
  }
}

/** Compact icon action button — same size across Preview / Arrange / header. */
function IconBtn({
  icon,
  title,
  label,
  className = 'secondary',
  pressed,
  selected,
  disabled,
  onClick,
  type = 'button',
  ...rest
}) {
  return (
    <button
      type={type}
      className={`icon-btn ${className}`.trim()}
      title={title}
      aria-label={label || title}
      aria-pressed={pressed}
      aria-selected={selected}
      disabled={disabled}
      onClick={onClick}
      {...rest}
    >
      {icon}
    </button>
  )
}

function KeyframesPanel({ img, apiRef }) {
  const [open, setOpen, rootRef] = useDismissableOpen(false)
  const [snap, setSnap] = useState({ selected: null, playing: false })
  const keyframes = img?.media_kind === 'video' ? (img.keyframes || []) : []

  useEffect(() => {
    if (!apiRef) return undefined
    const tick = () => {
      const a = apiRef.current
      const nextSelected = a?.selectedKfFrame ?? null
      const nextPlaying = Boolean(a?.playing)
      setSnap((prev) => {
        if (prev.selected === nextSelected && prev.playing === nextPlaying) return prev
        return { selected: nextSelected, playing: nextPlaying }
      })
    }
    tick()
    const id = window.setInterval(tick, 200)
    return () => window.clearInterval(id)
  }, [apiRef, img?.id, keyframes.length])

  if (!img || img.media_kind !== 'video' || !keyframes.length) return null

  const selectedOrd = snap.selected != null
    ? keyframes.findIndex((k) => Number(k.frame) === Number(snap.selected)) + 1
    : 0
  const summary = selectedOrd > 0
    ? `${selectedOrd}/${keyframes.length}`
    : `—/${keyframes.length}`

  return (
    <div className="image-facts keyframes-panel" ref={rootRef}>
      <button
        type="button"
        className="facts-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title="Select a keyframe to edit"
      >
        <span className="facts-role">Keyframes</span>
        <span>{summary}</span>
        <span className="facts-caret" aria-hidden="true">{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div className="facts-panel keyframes-facts-panel">
          <div>
            <div className="panel-section-label">Select</div>
            <div className="row wrap preview-kf-select" role="group" aria-label="Keyframes">
              {keyframes.map((kf, i) => {
                const n = i + 1
                const isSelected = Number(snap.selected) === Number(kf.frame)
                return (
                  <button
                    key={`akf-${kf.frame}`}
                    type="button"
                    className={isSelected ? '' : 'secondary'}
                    aria-pressed={isSelected}
                    title={`Keyframe ${n} (frame ${kf.frame})`}
                    disabled={snap.playing}
                    onClick={() => {
                      const frame = Number(kf.frame)
                      setSnap((s) => ({ ...s, selected: frame }))
                      apiRef?.current?.selectKeyframe?.(frame)
                    }}
                  >
                    {n}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </div>
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

function VideoScrubber({
  img, onSession, onLocalWork, onError, pending, onSelectKeyframe,
}) {
  const trackRef = useRef(null)
  const dragRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [activeHandle, setActiveHandle] = useState('in')
  const [localIn, setLocalIn] = useState(img?.in_frame ?? 0)
  const [localOut, setLocalOut] = useState(img?.out_frame ?? 0)
  const localRef = useRef({ in: 0, out: 0 })
  const [kfMenu, setKfMenu] = useState(null)
  const [draggingKf, setDraggingKf] = useState(null)

  const keyframes = img?.keyframes || []
  const workFrame = img?.work_frame ?? localIn

  useEffect(() => {
    const max = Math.max(0, (img?.frame_count || 1) - 1)
    const nextIn = img?.in_frame ?? 0
    const nextOut = img?.out_frame ?? max
    setLocalIn(nextIn)
    setLocalOut(nextOut)
    localRef.current = { in: nextIn, out: nextOut }
    setActiveHandle('in')
    setKfMenu(null)
    onLocalWork?.(nextIn)
  }, [img?.id, img?.in_frame, img?.out_frame, img?.frame_count, img?.filename])

  useEffect(() => {
    localRef.current = { in: localIn, out: localOut }
  }, [localIn, localOut])

  function currentFocal() {
    const base = focalFromImage(img, pending)
    return {
      x: base.x,
      y: base.y,
      cropScale: clampCropScale(base.cropScale ?? img?.crop_scale ?? DEFAULT_CROP_SCALE),
    }
  }

  if (!img || img.media_kind !== 'video') return null
  const frameCount = Math.max(1, img.frame_count || 1)
  const maxFrame = frameCount - 1
  const inF = Math.max(0, Math.min(maxFrame, localIn))
  const outF = Math.max(inF, Math.min(maxFrame, localOut))

  function frameFromClientX(clientX) {
    const el = trackRef.current
    if (!el) return 0
    const rect = el.getBoundingClientRect()
    const t = rect.width > 0 ? (clientX - rect.left) / rect.width : 0
    return Math.round(Math.max(0, Math.min(1, t)) * maxFrame)
  }

  function pctFor(frame) {
    return maxFrame > 0 ? (frame / maxFrame) * 100 : 0
  }

  function showFrame(which, inVal, outVal) {
    onLocalWork?.(which === 'out' ? outVal : inVal)
  }

  function applyDrag(which, clientX) {
    const f = frameFromClientX(clientX)
    const prev = dragRef.current
    let curIn = prev?.in ?? inF
    let curOut = prev?.out ?? outF
    if (which === 'in') {
      curIn = Math.min(f, curOut)
      setLocalIn(curIn)
    } else {
      curOut = Math.max(f, curIn)
      setLocalOut(curOut)
    }
    dragRef.current = { which, in: curIn, out: curOut }
    showFrame(which, curIn, curOut)
  }

  function onPointerDown(which, e) {
    if (busy) return
    e.preventDefault()
    e.stopPropagation()
    setActiveHandle(which)
    setKfMenu(null)
    e.currentTarget.setPointerCapture?.(e.pointerId)
    const startX = e.clientX
    applyDrag(which, e.clientX)
    dragRef.current = { ...dragRef.current, startX, moved: false }
  }

  function onPointerMove(e) {
    if (draggingKf != null) {
      const f = Math.max(inF, Math.min(outF, frameFromClientX(e.clientX)))
      dragRef.current = { ...(dragRef.current || {}), kf: true, kfTo: f }
      onLocalWork?.(f)
      return
    }
    if (!dragRef.current || dragRef.current.kf) return
    if (!dragRef.current.which) return
    if (dragRef.current.startX != null && Math.abs(e.clientX - dragRef.current.startX) > 4) {
      dragRef.current.moved = true
    }
    applyDrag(dragRef.current.which, e.clientX)
  }

  async function onPointerUp() {
    if (draggingKf != null) {
      const from = draggingKf
      const to = dragRef.current?.kfTo ?? from
      setDraggingKf(null)
      dragRef.current = null
      if (to !== from) {
        setBusy(true)
        try {
          await flushLocalRangeIfNeeded()
          const next = await api.videoKeyframeMove({ index: img.id, from_frame: from, to_frame: to })
          onSession(next)
        } catch (err) {
          onError?.(err.message)
        } finally {
          setBusy(false)
        }
      }
      return
    }
    const drag = dragRef.current
    dragRef.current = null
    if (!drag || drag.kf) return
    const nextIn = Math.max(0, Math.min(maxFrame, drag.in))
    const nextOut = Math.max(nextIn, Math.min(maxFrame, drag.out))
    setLocalIn(nextIn)
    setLocalOut(nextOut)
    localRef.current = { in: nextIn, out: nextOut }
    showFrame(drag.which, nextIn, nextOut)
    // Persist trim so endpoint keyframes remap with the handles (never create markers).
    if (drag.moved) {
      setBusy(true)
      try {
        await flushLocalRangeIfNeeded()
      } catch (err) {
        onError?.(err.message)
      } finally {
        setBusy(false)
      }
      return
    }
    // Click In/Out → ease popover only (no keyframe create).
    if (drag.which === 'in' || drag.which === 'out') {
      await openEndpointMenu(drag.which)
    }
  }

  async function flushLocalRangeIfNeeded() {
    const li = localRef.current.in
    const lo = localRef.current.out
    if ((img.in_frame ?? 0) === li && (img.out_frame ?? maxFrame) === lo) return null
    const next = await api.videoRange({
      index: img.id,
      in_frame: li,
      out_frame: lo,
      work_frame: Math.max(li, Math.min(lo, workFrame)),
    })
    onSession(next)
    return next
  }

  async function openEndpointMenu(which) {
    const frame = which === 'out' ? localRef.current.out : localRef.current.in
    setActiveHandle(which)
    setBusy(true)
    try {
      await flushLocalRangeIfNeeded()
      const sought = await api.videoRange({ index: img.id, work_frame: frame })
      onSession(sought)
      const entry = sought.images?.find((im) => im.id === img.id) || img
      const existing = (entry.keyframes || []).find((k) => Number(k.frame) === frame)
      // Seek + load focal for editing — never create a keyframe here.
      if (existing) {
        onSelectKeyframe?.(existing)
        setKfMenu({ frame, leftPct: pctFor(frame) })
      } else {
        setKfMenu(null)
      }
    } catch (err) {
      onError?.(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function onTrackClick(e) {
    if (busy) return
    if (e.target.closest('.video-scrubber-handle') || e.target.closest('.video-kf-marker')) return
    const f = frameFromClientX(e.clientX)
    if (e.shiftKey) {
      if (f < inF || f > outF) return
      const focal = currentFocal()
      setBusy(true)
      try {
        await flushLocalRangeIfNeeded()
        const next = await api.videoKeyframe({
          index: img.id,
          frame: f,
          focal_x: focal.x,
          focal_y: focal.y,
          crop_scale: focal.cropScale,
        })
        onSession(next)
        setKfMenu({ frame: f, leftPct: pctFor(f) })
      } catch (err) {
        onError?.(err.message)
      } finally {
        setBusy(false)
      }
      return
    }
    const wf = Math.max(inF, Math.min(outF, f))
    onLocalWork?.(wf)
    try {
      const next = await api.videoRange({ index: img.id, work_frame: wf })
      onSession(next)
    } catch (err) {
      onError?.(err.message)
    }
  }

  function onKfPointerDown(frame, e) {
    if (busy) return
    e.preventDefault()
    e.stopPropagation()
    setDraggingKf(frame)
    dragRef.current = { kf: true, kfFrom: frame, kfTo: frame }
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }

  async function onKfClick(frame, e) {
    e.preventDefault()
    e.stopPropagation()
    if (draggingKf != null) return
    setKfMenu({ frame, leftPct: pctFor(frame) })
    // Seek first (drops stale pending), then load this keyframe's focal.
    onLocalWork?.(frame)
    const localKf = (img.keyframes || []).find((k) => Number(k.frame) === frame)
    if (localKf) onSelectKeyframe?.(localKf)
    try {
      const next = await api.videoRange({ index: img.id, work_frame: frame })
      onSession(next)
      const entry = next.images?.find((im) => im.id === img.id) || img
      const kf = (entry.keyframes || []).find((k) => Number(k.frame) === frame)
      if (kf) onSelectKeyframe?.(kf)
    } catch (err) {
      onError?.(err.message)
    }
  }

  async function setEase(frame, ease) {
    setBusy(true)
    try {
      const next = await api.videoKeyframeEase({ index: img.id, frame, ease })
      onSession(next)
    } catch (err) {
      onError?.(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function deleteKf(frame) {
    if (frame === inF || frame === outF) return
    setBusy(true)
    try {
      await flushLocalRangeIfNeeded()
      const next = await api.videoKeyframeDelete({ index: img.id, frame })
      onSession(next)
      setKfMenu(null)
    } catch (err) {
      onError?.(err.message)
    } finally {
      setBusy(false)
    }
  }

  const inPct = pctFor(inF)
  const outPct = pctFor(outF)
  const workPct = pctFor(Math.max(inF, Math.min(outF, workFrame)))
  // In/Out are keyframes in data, but only mid frames get diamond markers.
  const midKeyframes = keyframes.filter((k) => {
    const f = Number(k.frame)
    return f !== inF && f !== outF
  })
  const activeKf = keyframes.find((k) => Number(k.frame) === kfMenu?.frame)
  const activeIsEndpoint = Boolean(activeKf && (Number(activeKf.frame) === inF || Number(activeKf.frame) === outF))

  return (
    <div className="video-scrubber">
      <div
        className="video-scrubber-track-wrap"
        ref={trackRef}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onClick={onTrackClick}
      >
        <div className="video-scrubber-rail" />
        <div
          className="video-scrubber-range"
          style={{ left: `${inPct}%`, width: `${Math.max(0, outPct - inPct)}%` }}
        />
        {midKeyframes.map((kf) => {
          const showF = draggingKf === kf.frame && dragRef.current?.kfTo != null
            ? dragRef.current.kfTo
            : kf.frame
          return (
            <button
              key={`kf-${kf.frame}`}
              type="button"
              className={`video-kf-marker${kfMenu?.frame === kf.frame ? ' is-active' : ''}`}
              style={{ left: `${pctFor(showF)}%` }}
              disabled={busy}
              title={`Keyframe @ ${kf.frame} (${kf.ease || DEFAULT_KEYFRAME_EASE})`}
              aria-label={`Keyframe at frame ${kf.frame}`}
              onPointerDown={(e) => onKfPointerDown(kf.frame, e)}
              onClick={(e) => onKfClick(kf.frame, e)}
            />
          )
        })}
        <button
          type="button"
          className="video-scrubber-handle work"
          style={{ left: `${workPct}%` }}
          disabled={busy}
          aria-label="Work frame"
          title={`Work frame ${workFrame}`}
          onPointerDown={(e) => { e.preventDefault(); e.stopPropagation() }}
        />
        <button
          type="button"
          className={`video-scrubber-handle in${activeHandle === 'in' ? ' is-active' : ''}${kfMenu?.frame === inF ? ' is-kf-active' : ''}`}
          style={{ left: `${inPct}%` }}
          disabled={busy}
          aria-label="Start frame keyframe"
          aria-pressed={activeHandle === 'in'}
          title="Drag to set In · click for ease curve"
          onPointerDown={(e) => onPointerDown('in', e)}
        />
        <button
          type="button"
          className={`video-scrubber-handle out${activeHandle === 'out' ? ' is-active' : ''}${kfMenu?.frame === outF ? ' is-kf-active' : ''}`}
          style={{ left: `${outPct}%` }}
          disabled={busy}
          aria-label="End frame keyframe"
          aria-pressed={activeHandle === 'out'}
          title="Drag to set Out · click for ease curve"
          onPointerDown={(e) => onPointerDown('out', e)}
        />
        {kfMenu && activeKf && (
          <div
            className="video-kf-popover"
            style={{ left: `${kfMenu.leftPct}%` }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="video-kf-popover-title">
              {activeIsEndpoint
                ? (activeKf.frame === inF ? 'Start' : 'End')
                : `Frame ${activeKf.frame}`}
            </div>
            <div className="video-kf-ease" role="group" aria-label="Outgoing ease">
              {KEYFRAME_EASES.map((ease) => (
                <button
                  key={ease}
                  type="button"
                  className={(activeKf.ease || DEFAULT_KEYFRAME_EASE) === ease ? '' : 'secondary'}
                  aria-pressed={(activeKf.ease || DEFAULT_KEYFRAME_EASE) === ease}
                  disabled={busy}
                  onClick={() => setEase(activeKf.frame, ease)}
                >
                  {ease}
                </button>
              ))}
            </div>
            <div className="video-kf-popover-actions">
              <button type="button" className="secondary" disabled={busy} onClick={() => setKfMenu(null)}>Close</button>
              {!activeIsEndpoint && (
                <button type="button" disabled={busy} onClick={() => deleteKf(activeKf.frame)}>Delete</button>
              )}
            </div>
          </div>
        )}
      </div>
      <div className="video-scrubber-row">
        <span className="muted video-scrubber-meta">
          {activeHandle === 'in' ? 'start' : 'end'} {activeHandle === 'in' ? inF : outF}
          {' · '}
          {inF}–{outF} / {maxFrame}
          {keyframes.length ? ` · ${keyframes.length} kf` : ''}
          {img.fps ? ` · ${Number(img.fps).toFixed(1)} fps` : ''}
        </span>
        <span className="muted video-scrubber-hint">Shift+click add keyframe</span>
      </div>
    </div>
  )
}

function FocalStage({
  session, pending, setPending, onConfirm, onSaveKeyframe, onDiscard, showGrid,
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
      const next = {
        ...base,
        index: img.id,
        autoCenter: false,
        cropScale: nudgeCropScale(base.cropScale ?? DEFAULT_CROP_SCALE, e.deltaY),
      }
      if (img.media_kind === 'video') {
        next.keyframeFrame = base.keyframeFrame ?? pendingRef.current?.keyframeFrame ?? img.work_frame ?? 0
      }
      setPending(next)
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
    const x = Math.max(0, Math.min(origW, (lx / layout.dw) * origW))
    const y = Math.max(0, Math.min(origH, (ly / layout.dh) * origH))
    const pt = withCropScale({ x, y, autoCenter: false }, img, pendingRef.current)
    if (img.media_kind === 'video') {
      pt.keyframeFrame = pendingRef.current?.keyframeFrame ?? img.work_frame ?? 0
    }
    return pt
  }

  function centerPending() {
    const { origW, origH } = sourceSize()
    const pt = withCropScale({ x: origW / 2, y: origH / 2, autoCenter: true }, img, pendingRef.current)
    if (img?.media_kind === 'video') {
      pt.keyframeFrame = pendingRef.current?.keyframeFrame ?? img.work_frame ?? 0
    }
    return pt
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
      // Videos: write the keyframe as soon as the focal moves (click or drag).
      if (img?.media_kind === 'video' && onSaveKeyframe) {
        const pt = pendingRef.current
        if (pt) onSaveKeyframe(pt)
      }
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
  session, onCommit, onSession, onError, showGrid, draftFlushRef,
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
  const viewRef = useRef({ x: 0, y: 0, cropScale: 1, flipH: false, flipV: false })
  const img = session.images[session.current_idx]
  const prevImg = session.images[session.current_idx - 1]
  const nextImg = session.images[session.current_idx + 1]
  const isVideo = img?.media_kind === 'video'
  const [playFrame, setPlayFrame] = useState(null)
  const [playing, setPlaying] = useState(false)
  const [selectedKfFrame, setSelectedKfFrame] = useState(null)
  const keyframes = isVideo ? (img?.keyframes || []) : []
  const selectedKfRef = useRef(selectedKfFrame)
  selectedKfRef.current = selectedKfFrame
  const displayFrame = isVideo
    ? (playFrame != null ? playFrame : (img.work_frame ?? 0))
    : 0
  // Freeze the <img> URL while playing — frames are painted from a prefetch
  // loop so thrashing src would only race the canvas.
  const sourceSrc = img
    ? (isVideo
      ? mediaUrl(
        'frame',
        img.id,
        `?frame=${playing ? (img.work_frame ?? displayFrame) : displayFrame}&n=${encodeURIComponent(img.filename)}&wf=${playing ? (img.work_frame ?? displayFrame) : displayFrame}`,
      )
      : mediaUrl('original', img.id, `?n=${encodeURIComponent(img.filename)}`))
    : ''
  const committed = useMemo(() => {
    const kfs = img?.keyframes || []
    const kf = selectedKfFrame != null
      ? kfs.find((k) => Number(k.frame) === selectedKfFrame)
      : null
    if (kf) {
      return {
        x: kf.focal_x,
        y: kf.focal_y,
        cropScale: clampCropScale(kf.crop_scale ?? DEFAULT_CROP_SCALE),
        flipH: Boolean(img?.flip_h),
        flipV: Boolean(img?.flip_v),
      }
    }
    return {
      x: img?.focal?.[0] ?? (img?.width || 0) / 2,
      y: img?.focal?.[1] ?? (img?.height || 0) / 2,
      cropScale: clampCropScale(img?.crop_scale ?? DEFAULT_CROP_SCALE),
      flipH: Boolean(img?.flip_h),
      flipV: Boolean(img?.flip_v),
    }
  }, [img, selectedKfFrame])
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

  useEffect(() => {
    setCompare(false)
    setNeighbor(0)
    setFocalPulse(0)
    setPlaying(false)
    setPlayFrame(null)
    setSelectedKfFrame(null)
  }, [img?.id])

  useEffect(() => {
    setDraft(committed)
  }, [img?.id, committed.x, committed.y, committed.cropScale, committed.flipH, committed.flipV])

  function clearCanvas() {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, canvas.width || 0, canvas.height || 0)
  }

  function drawDecoded(image, frameForInterp = null) {
    const canvas = canvasRef.current
    const viewport = viewportRef.current
    const stage = stageRef.current
    if (!img || !canvas || !image || !viewport || !stage) return false
    if (!image.complete || !image.naturalWidth) return false
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
    let vx = viewRef.current.x
    let vy = viewRef.current.y
    let vScale = viewRef.current.cropScale
    if (frameForInterp != null && img.keyframes?.length) {
      const interp = interpolateFromKeyframes(img.keyframes, frameForInterp)
      if (interp) {
        vx = interp.x
        vy = interp.y
        vScale = interp.cropScale
      }
    }
    const crop = computeCrop(
      vx, vy, w, h,
      target.w, target.h, vScale,
    )
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, dw, dh)
    ctx.save()
    const { flipH, flipV } = viewRef.current
    if (flipH || flipV) {
      ctx.translate(flipH ? dw : 0, flipV ? dh : 0)
      ctx.scale(flipH ? -1 : 1, flipV ? -1 : 1)
    }
    ctx.drawImage(image, crop.x, crop.y, crop.w, crop.h, 0, 0, dw, dh)
    ctx.restore()
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
    return true
  }

  useEffect(() => {
    if (!playing || !isVideo || !img) return undefined
    let cancelled = false
    const inF = img.in_frame ?? 0
    const outF = img.out_frame ?? Math.max(0, (img.frame_count || 1) - 1)
    const fps = Math.max(1, Math.min(30, Number(img.fps) || 24))
    let frame = Math.max(inF, Math.min(outF, playFrame != null ? playFrame : (img.work_frame ?? inF)))
    setPlayFrame(frame)
    setSourceReady(true)

    const urlFor = (f) => mediaUrl(
      'frame',
      img.id,
      `?frame=${f}&n=${encodeURIComponent(img.filename)}&wf=${f}`,
    )

    function loadFrame(f) {
      return new Promise((resolve, reject) => {
        const im = new Image()
        im.onload = () => resolve(im)
        im.onerror = () => reject(new Error(`frame ${f}`))
        im.src = urlFor(f)
      })
    }

    ;(async () => {
      const cache = new Map()
      const ensure = async (f) => {
        if (cache.has(f)) return cache.get(f)
        const p = loadFrame(f)
        cache.set(f, p)
        if (cache.size > 12) {
          const first = cache.keys().next().value
          cache.delete(first)
        }
        return p
      }
      while (!cancelled) {
        const t0 = performance.now()
        try {
          const im = await ensure(frame)
          if (cancelled) break
          drawDecoded(im, frame)
          setPlayFrame(frame)
          const next = frame >= outF ? inF : frame + 1
          ensure(next).catch(() => {})
        } catch {
          // Keep last painted frame rather than blanking.
        }
        frame = frame >= outF ? inF : frame + 1
        const wait = Math.max(0, (1000 / fps) - (performance.now() - t0))
        await new Promise((r) => setTimeout(r, wait))
      }
    })()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, isVideo, img?.id, img?.in_frame, img?.out_frame, img?.fps])

  async function togglePlay() {
    if (!isVideo) return
    if (playing) {
      setPlaying(false)
      const frame = playFrame != null ? playFrame : (img.work_frame ?? 0)
      try {
        const next = await api.videoRange({ index: img.id, work_frame: frame })
        onSession?.(next)
        setPlayFrame(null)
      } catch (err) {
        onError?.(err.message || String(err))
      }
      return
    }
    setPlaying(true)
  }

  async function selectKeyframe(frame) {
    if (!isVideo || playing) return false
    const kf = (img.keyframes || []).find((k) => Number(k.frame) === Number(frame))
    if (!kf) return false
    setSelectedKfFrame(kf.frame)
    setDraft((d) => ({
      ...d,
      x: kf.focal_x,
      y: kf.focal_y,
      cropScale: clampCropScale(kf.crop_scale),
    }))
    setCompare(false)
    setPlayFrame(kf.frame)
    try {
      const next = await api.videoRange({ index: img.id, work_frame: kf.frame })
      onSession?.(next)
    } catch (err) {
      onError?.(err.message || String(err))
      return false
    }
    return true
  }

  const togglePlayRef = useRef(togglePlay)
  togglePlayRef.current = togglePlay
  const selectKeyframeRef = useRef(selectKeyframe)
  selectKeyframeRef.current = selectKeyframe

  useEffect(() => {
    // During playback we paint from prefetched Images — don't wipe the stage
    // every time the reactive frame URL changes.
    if (playing && isVideo) return undefined
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
  }, [img?.id, sourceSrc, playing, isVideo])

  const view = compare ? committed : draft
  viewRef.current = view
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
        keyframeFrame: selectedKfRef.current,
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
      togglePlay: () => {
        togglePlayRef.current?.()
        return true
      },
      selectKeyframe: (frame) => selectKeyframeRef.current?.(frame),
      playing,
      isVideo,
      selectedKfFrame,
    }
    return () => {
      if (compareApiRef) compareApiRef.current = null
    }
  }, [dirty, compare, committing, compareApiRef, img?.focal, playing, isVideo, selectedKfFrame])

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
        keyframeFrame: selectedKfFrame,
      }
    } else {
      draftFlushRef.current = null
    }
    return () => {
      if (draftFlushRef) draftFlushRef.current = null
    }
  }, [dirty, draft.x, draft.y, draft.cropScale, draft.flipH, draft.flipV, img, draftFlushRef, selectedKfFrame])

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
    // Playback paints via drawDecoded from prefetched frames — leave the
    // last good frame on the canvas instead of racing the <img> src churn.
    if (playing && isVideo) return
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
    // Focal stays in unflipped EXIF space; flip the drawn crop to match export
    // (flip image then crop around transformed focal ≡ crop then flip result).
    const crop = computeCrop(
      view.x, view.y, w, h,
      target.w, target.h, view.cropScale,
    )
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, dw, dh)
    ctx.save()
    if (view.flipH || view.flipV) {
      ctx.translate(view.flipH ? dw : 0, view.flipV ? dh : 0)
      ctx.scale(view.flipH ? -1 : 1, view.flipV ? -1 : 1)
    }
    ctx.drawImage(image, crop.x, crop.y, crop.w, crop.h, 0, 0, dw, dh)
    ctx.restore()
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
    const crop = computeCrop(
      draft.x, draft.y, w, h,
      target.w, target.h, draft.cropScale,
    )
    const sx = crop.w / canvas.clientWidth
    const sy = crop.h / canvas.clientHeight
    // Negate screen deltas under canvas flips so drag direction matches content.
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
    // Focal stays in unflipped space; canvas scale flips the preview (and export
    // applies the same flips to the full bitmap before cropping).
    setDraft((d) => {
      if (axis === 'h') return { ...d, flipH: !d.flipH }
      return { ...d, flipV: !d.flipV }
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

  const target = targetForMode(session)
  const zoomLabel = img.focal
    ? `${zoomFactor(
      view.x, view.y, img.width || 0, img.height || 0,
      target.w, target.h, view.cropScale,
    ).toFixed(2)}×`
    : '—'

  const prevDisabled = !prevImg || neighbor <= -1
  const nextDisabled = !nextImg || neighbor >= 1
  const overlayAmt = Math.round(neighborOpacity * 100)
  const prevOverlayTitle = !prevImg
    ? 'No previous overlay'
    : showPrev
      ? `Previous overlay · ${overlayAmt}%`
      : 'Previous overlay (−10%)'
  const nextOverlayTitle = !nextImg
    ? 'No next overlay'
    : showNext
      ? `Next overlay · ${overlayAmt}%`
      : 'Next overlay (+10%)'

  return (
    <div className="workspace preview">
      <div className="preview-toolbar">
        <div className="preview-toolbar-left">
          <IconBtn
            icon={<IconShowSlot />}
            title={
              !img.focal
                ? 'Set a focal on Original first'
                : dirty
                  ? 'Toggle saved vs draft framing (C)'
                  : 'Make a pan/zoom change to enable Compare'
            }
            label="Compare"
            selected={compare}
            disabled={Boolean(img.focal) && !dirty}
            onClick={() => {
              if (!img.focal) {
                nudgeNeedFocal()
                return
              }
              setCompare((v) => !v)
            }}
          />
          <IconBtn
            icon={<IconCommit />}
            title={!img.focal ? 'Set a focal on Original first' : committing ? 'Saving…' : 'Commit draft framing (Enter)'}
            label={committing ? 'Saving' : 'Commit'}
            className=""
            disabled={Boolean(img.focal) && (!dirty || committing || compare)}
            onClick={() => {
              if (!img.focal) {
                nudgeNeedFocal()
                return
              }
              commit()
            }}
          />
          <IconBtn
            icon={<IconFlipX />}
            title={!img.focal ? 'Set a focal on Original first' : 'Flip on the X axis (upside down)'}
            label="Flip X (upside down)"
            pressed={Boolean(view.flipV)}
            disabled={Boolean(img.focal) && compare}
            onClick={() => toggleFlip('v')}
          />
          <IconBtn
            icon={<IconFlipY />}
            title={!img.focal ? 'Set a focal on Original first' : 'Flip on the Y axis (left ↔ right)'}
            label="Flip Y (left ↔ right)"
            pressed={Boolean(view.flipH)}
            disabled={Boolean(img.focal) && compare}
            onClick={() => toggleFlip('h')}
          />
          <IconBtn
            icon={<IconZoomOut />}
            title={img.focal ? `Zoom out (now ${zoomLabel})` : 'Zoom out'}
            label="Zoom out"
            disabled={!img.focal || compare}
            onClick={() => nudgeZoom(1)}
          />
          <IconBtn
            icon={<IconZoomIn />}
            title={img.focal ? `Zoom in (now ${zoomLabel})` : 'Zoom in'}
            label="Zoom in"
            disabled={!img.focal || compare}
            onClick={() => nudgeZoom(-1)}
          />
        </div>
        <div className="preview-toolbar-center">
          <IconBtn
            icon={<IconOverlayPrev />}
            className="secondary icon-btn-overlay"
            title={prevOverlayTitle}
            label="Previous overlay"
            disabled={prevDisabled}
            onClick={() => stepNeighbor(-0.1)}
          />
          <IconBtn
            icon={<IconOverlayClear />}
            className="secondary icon-btn-overlay"
            title={neighbor === 0 ? 'No overlay' : `Clear overlay (${overlayAmt}%)`}
            label="Clear overlay"
            disabled={neighbor === 0}
            onClick={() => setNeighbor(0)}
          />
          <IconBtn
            icon={<IconOverlayNext />}
            className="secondary icon-btn-overlay"
            title={nextOverlayTitle}
            label="Next overlay"
            disabled={nextDisabled}
            onClick={() => stepNeighbor(0.1)}
          />
        </div>
        <div className="preview-toolbar-right">
          {isVideo && (
            <IconBtn
              icon={playing ? <IconPause /> : <IconPlay />}
              title={playing ? 'Pause playback (Space)' : 'Play in→out range (Space)'}
              label={playing ? 'Pause' : 'Play'}
              pressed={playing}
              onClick={() => togglePlay()}
            />
          )}
          <IconBtn
            icon={<IconWrap />}
            title={wrapNav ? 'Wrapping on: arrows loop the list' : 'Wrapping off: stop at first/last'}
            label={wrapNav ? 'Wrap on' : 'Wrap off'}
            pressed={wrapNav}
            onClick={() => setWrapNav((v) => !v)}
          />
        </div>
      </div>
      <div className="preview-viewport" ref={viewportRef}>
        <div
          className={`preview-frame ${img.focal && !compare ? 'interactive' : ''}${sourceReady ? '' : ' is-loading'}`}
          ref={stageRef}
          style={{ opacity: (sourceReady || (playing && isVideo)) ? 1 : 0 }}
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
          {isVideo && playing && (() => {
            const inF = img.in_frame ?? 0
            const outF = img.out_frame ?? Math.max(0, (img.frame_count || 1) - 1)
            const span = Math.max(1, outF - inF)
            const cur = Math.max(inF, Math.min(outF, displayFrame))
            const trimIdx = cur - inF
            const trimTotal = outF - inF
            const pct = (trimIdx / span) * 100
            return (
              <div
                className="preview-play-progress"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(pct)}
                title={`${trimIdx} / ${trimTotal} of trim`}
              >
                <div style={{ width: `${pct}%` }} />
                <span className="preview-play-fraction">{trimIdx}/{trimTotal}</span>
              </div>
            )
          })()}
        </div>
      </div>
    </div>
  )
}

export default function Aligner({ session, setSession, batchMode, onFinished, theme = 'dark', onToggleTheme }) {
  const [tab, setTab] = useState('original')
  const [pending, setPending] = useState(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportDone, setExportDone] = useState(false)
  const [resetOpen, setResetOpen] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [clearSlotOpen, setClearSlotOpen] = useState(false)
  const [clearSlotTarget, setClearSlotTarget] = useState(null)
  const [clearingSlot, setClearingSlot] = useState(false)
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
    const img = session.images[session.current_idx]
    const kfFrame = p.keyframeFrame != null
      ? p.keyframeFrame
      : (img?.media_kind === 'video' ? (img.work_frame ?? undefined) : undefined)
    const next = await api.setFocal({
      x: p.x,
      y: p.y,
      auto_center: Boolean(p.autoCenter),
      crop_scale: clampCropScale(p.cropScale ?? DEFAULT_CROP_SCALE),
      flip_h: p.flipH != null ? Boolean(p.flipH) : undefined,
      flip_v: p.flipV != null ? Boolean(p.flipV) : undefined,
      index: session.current_idx,
      keyframe_frame: kfFrame,
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
    // Drain progress events slowly so the float stays readable.
    const PROGRESS_DWELL_MS = 110
    let progressChain = Promise.resolve()
    const enqueueProgress = (fn) => {
      progressChain = progressChain.then(async () => {
        fn()
        await new Promise((r) => window.setTimeout(r, PROGRESS_DWELL_MS))
      })
    }
    try {
      const res = await api.arrangeAuto({ mode, ...extra })
      const next = await readSse(res, (ev) => {
        if (ev.phase === 'start' || ev.phase === 'progress') {
          const done = ev.done ?? 0
          const total = ev.total || session.total || 1
          const filename = ev.filename || ''
          enqueueProgress(() => {
            setArrangeProgress({ done, total, filename })
            if (filename && !String(filename).endsWith('…')) {
              setArrangeStatus(`${busyMsg.replace(/…$/, '')} · ${done}/${total}`)
            } else if (filename) {
              setArrangeStatus(String(filename))
            }
          })
        }
        if (ev.phase === 'error' || ev.error) {
          setError(ev.error || 'AutoArrange failed')
        }
      })
      await progressChain
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

  const openClearSlot = (slot) => {
    const target = String(slot || session.arrangement_active || 'original')
    if (target === 'original' || target === '0') return
    if (!session.arrangements?.[target]) return
    setClearSlotTarget(target)
    setClearSlotOpen(true)
  }

  const confirmClearSlot = async () => {
    const slot = clearSlotTarget || session.arrangement_active || 'original'
    if (slot === 'original' || slot === '0') {
      setClearSlotOpen(false)
      return
    }
    setClearingSlot(true)
    setError('')
    try {
      apply(await api.arrangeClear({ slot }))
      setClearSlotOpen(false)
      setClearSlotTarget(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setClearingSlot(false)
    }
  }

  const activeArrangeSlot = session.arrangement_active || 'original'
  const activeArrangeMethod = session.arrangement_methods?.[activeArrangeSlot] || null
  const activeArrangeModified = Boolean(session.arrangement_modified?.[activeArrangeSlot])

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
    const img = session.images[session.current_idx]
    const kfFrame = pt.keyframeFrame != null
      ? pt.keyframeFrame
      : (img?.media_kind === 'video' ? (img.work_frame ?? undefined) : undefined)
    await api.setFocal({
      x: pt.x,
      y: pt.y,
      auto_center: Boolean(pt.autoCenter),
      crop_scale: clampCropScale(pt.cropScale ?? DEFAULT_CROP_SCALE),
      index: session.current_idx,
      keyframe_frame: kfFrame,
    })
    apply(await api.confirm())
    return null
  }

  /** Persist focal to the current video keyframe without advancing. */
  const saveKeyframeFocal = async (pt) => {
    const img = session.images[session.current_idx]
    if (!img || img.media_kind !== 'video') return null
    const kfFrame = pt.keyframeFrame != null ? pt.keyframeFrame : (img.work_frame ?? 0)
    const next = await api.setFocal({
      x: pt.x,
      y: pt.y,
      auto_center: Boolean(pt.autoCenter),
      crop_scale: clampCropScale(pt.cropScale ?? DEFAULT_CROP_SCALE),
      index: session.current_idx,
      keyframe_frame: kfFrame,
    })
    setSession(next)
    setPending({
      x: pt.x,
      y: pt.y,
      cropScale: clampCropScale(pt.cropScale ?? DEFAULT_CROP_SCALE),
      autoCenter: Boolean(pt.autoCenter),
      index: img.id,
      keyframeFrame: kfFrame,
    })
    return next
  }

  const commitPreview = async (pt) => {
    const img = session.images[session.current_idx]
    const kfFrame = pt.keyframeFrame != null
      ? pt.keyframeFrame
      : (img?.media_kind === 'video' ? (img.work_frame ?? undefined) : undefined)
    const next = await api.setFocal({
      x: pt.x,
      y: pt.y,
      auto_center: Boolean(pt.autoCenter),
      crop_scale: clampCropScale(pt.cropScale ?? DEFAULT_CROP_SCALE),
      flip_h: Boolean(pt.flipH),
      flip_v: Boolean(pt.flipV),
      index: session.current_idx,
      keyframe_frame: kfFrame,
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
    if (clearSlotOpen) {
      if (e.key === 'Escape') {
        e.preventDefault()
        if (!clearingSlot) setClearSlotOpen(false)
      }
      return
    }
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
        e.preventDefault()
        const img = session.images[session.current_idx]
        await confirmPt(focalFromImage(img, pending))
      } else if (k === ' ') {
        e.preventDefault()
        if (tab === 'preview') {
          previewCompareRef.current?.togglePlay?.()
          return
        }
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
      } else if (k === 'Delete' || k === 'Backspace') {
        if (tab === 'arrange') {
          e.preventDefault()
          const active = session.arrangement_active || 'original'
          if (active !== 'original' && active !== '0' && session.arrangements?.[active]) {
            setClearSlotTarget(active)
            setClearSlotOpen(true)
          }
          return
        }
        apply(await api.clearFocal(session.current_idx))
      } else if (k === 'p' || k === 'P') await switchTab(tab === 'preview' ? 'original' : 'preview')
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
        if (tab === 'preview') {
          const api = previewCompareRef.current
          if (!session.images[session.current_idx]?.focal) api?.nudgeNeedFocal?.()
          else api?.toggle?.()
        }
      } else if (/^[0-6]$/.test(k)) {
        e.preventDefault()
        await recallSlot(k === '0' ? 'original' : k)
      } else if (k === 'Escape') onFinished()
    } catch (err) {
      setError(err.message)
    }
  }, [session, pending, tab, exportOpen, resetOpen, resetting, clearSlotOpen, clearingSlot, onFinished, setShowGrid, maskImage, previewWrap])

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
          <IconBtn
            icon={theme === 'dark' ? <IconSun /> : <IconMoon />}
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            label={theme === 'dark' ? 'Light mode' : 'Dark mode'}
            onClick={() => onToggleTheme?.()}
          />
          <IconBtn
            icon={<IconExport />}
            title="Export aligned media (E)"
            label="Export"
            disabled={exporting}
            onClick={() => { setExportOpen(true); setExportDone(false); setProgress(null); setExportError('') }}
          />
          <IconBtn
            icon={<IconDone />}
            title={batchMode ? 'Done — next folder (Esc)' : 'Done — back to opener (Esc)'}
            label="Done"
            onClick={onFinished}
          />
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
        {tab === 'original' && (
          <IconBtn
            className="secondary action-bar-end"
            icon={<IconDuplicate />}
            title="Duplicate current media after this one (D)"
            label="Duplicate"
            onClick={() => duplicateCurrent().catch((err) => setError(err.message))}
          />
        )}
        {tab === 'arrange' && (
          <div className="arrange-action-cluster">
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
            <IconBtn
              icon={<IconArrangeColor />}
              title={activeArrangeMethod === 'color'
                ? (activeArrangeModified ? 'Color — current slot (modified)' : 'Color — current slot')
                : 'Color'}
              label="Color"
              className={activeArrangeMethod === 'color' ? '' : 'secondary'}
              selected={activeArrangeMethod === 'color'}
              disabled={arrangeBusy}
              onClick={() => runAutoArrange('color')}
            />
            <IconBtn
              icon={<IconArrangeDepth />}
              title={activeArrangeMethod === 'depth'
                ? (activeArrangeModified ? 'Depth — current slot (modified)' : 'Depth — current slot')
                : 'Depth'}
              label="Depth"
              className={activeArrangeMethod === 'depth' ? '' : 'secondary'}
              selected={activeArrangeMethod === 'depth'}
              disabled={arrangeBusy}
              onClick={() => runAutoArrange('depth', { near_to_far: true })}
            />
            <IconBtn
              icon={<IconArrangeLead />}
              title={activeArrangeMethod === 'lead'
                ? (activeArrangeModified ? 'Lead — current slot (modified)' : 'Lead — current slot')
                : 'Lead'}
              label="Lead"
              className={activeArrangeMethod === 'lead' ? '' : 'secondary'}
              selected={activeArrangeMethod === 'lead'}
              disabled={arrangeBusy}
              onClick={() => runAutoArrange('lead', { lead_index: session.current_idx, axis: 'x' })}
              onMouseEnter={() => setLeadHover(true)}
              onMouseLeave={() => setLeadHover(false)}
              onFocus={() => setLeadHover(true)}
              onBlur={() => setLeadHover(false)}
            />
            <IconBtn
              icon={<IconArrangeFaces />}
              title={activeArrangeMethod === 'faces'
                ? (activeArrangeModified ? 'Faces — current slot (modified)' : 'Faces — current slot')
                : 'Faces'}
              label="Faces"
              className={activeArrangeMethod === 'faces' ? '' : 'secondary'}
              selected={activeArrangeMethod === 'faces'}
              disabled={arrangeBusy}
              onClick={() => runAutoArrange('faces')}
            />
            <div className="image-facts arrange-menu" ref={arrangeMenuRef}>
              <button
                type="button"
                className="facts-toggle"
                onClick={() => setArrangeMenuOpen((v) => !v)}
                aria-expanded={arrangeMenuOpen}
                title="AutoArrange info"
              >
                <span className="facts-role">Info</span>
                <span className="facts-caret" aria-hidden="true">{arrangeMenuOpen ? '▴' : '▾'}</span>
              </button>
              {arrangeMenuOpen && (
                <div className="facts-panel arrange-menu-panel">
                  <div className="arrange-menu-info" role="note">
                    <p><strong>Color</strong> — groups by HSV buckets (white / gray / black / hue).</p>
                    <p><strong>Depth</strong> — Depth-Anything near→far; use Reverse for far→near.</p>
                    <p><strong>Lead</strong> — ORB feature match against the selected thumbnail.</p>
                    <p><strong>Faces</strong> — left→right by detected face centers (YuNet).</p>
                    <p><strong>Slots 0–6</strong> — store and recall arrangements; leaving Arrange commits a manual draft.</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
        {tab === 'preview' && (
          <KeyframesPanel img={img} apiRef={previewCompareRef} />
        )}
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
              onSaveKeyframe={(pt) => saveKeyframeFocal(pt).catch((err) => setError(err.message))}
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
              pending={pending}
              onSelectKeyframe={(kf) => {
                setPending({
                  x: Number(kf.focal_x),
                  y: Number(kf.focal_y),
                  cropScale: clampCropScale(kf.crop_scale ?? DEFAULT_CROP_SCALE),
                  autoCenter: false,
                  index: img.id,
                  keyframeFrame: Number(kf.frame),
                })
              }}
              onSession={(next) => setSession(next)}
              onLocalWork={(wf) => {
                setPending((prev) => {
                  if (!prev || prev.index !== img.id) return prev
                  if (prev.keyframeFrame != null && Number(prev.keyframeFrame) === Number(wf)) return prev
                  return null
                })
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
          onSession={(next) => setSession(next)}
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
                <IconBtn
                  icon={<IconViewOriginal />}
                  title="Show original thumbnails"
                  label="Original view"
                  selected={arrangeView === 'original'}
                  onClick={() => setArrangeView('original')}
                />
                <IconBtn
                  icon={<IconViewAligned />}
                  title="Show aligned thumbnails"
                  label="Aligned view"
                  selected={arrangeView === 'aligned'}
                  onClick={() => setArrangeView('aligned')}
                />
                <IconBtn
                  icon={<IconSwap />}
                  title={session.arrangement_reversed ? 'Order is reversed — click to restore' : 'Reverse current order in place (updates active slot)'}
                  label="Reverse order"
                  className={session.arrangement_reversed ? '' : 'secondary'}
                  selected={Boolean(session.arrangement_reversed)}
                  disabled={arrangeBusy || session.total < 2}
                  onClick={() => reverseArrange().catch((err) => setError(err.message))}
                />
              </div>
              <div className="arrange-toolbar-center arrange-menu-slots">
                {ARRANGEMENT_SLOTS.map((slot) => {
                  const filled = slot === 'original' || Boolean(session.arrangements?.[slot])
                  const active = (session.arrangement_active || 'original') === slot
                  const method = session.arrangement_methods?.[slot]
                  const modified = Boolean(session.arrangement_modified?.[slot])
                  const methodName = arrangeMethodLabel(method)
                  const label = slot === 'original' ? 'OG (Original)' : `Slot ${slot}`
                  const title = [
                    label,
                    methodName || null,
                    modified ? 'Modified' : null,
                  ].filter(Boolean).join(' · ')
                  return (
                    <button
                      key={slot}
                      type="button"
                      className={`arrange-slot-btn${active ? ' is-active' : ' secondary'}${modified ? ' is-modified' : ''}`}
                      disabled={!filled}
                      title={title}
                      aria-label={title}
                      onClick={() => recallSlot(slot)}
                    >
                      <span className="arrange-slot-num">{slot === 'original' ? 'OG' : slot}</span>
                      {method ? (
                        <span className="arrange-slot-method" aria-hidden="true">
                          {arrangeMethodIcon(method)}
                        </span>
                      ) : null}
                      {modified ? (
                        <span className="arrange-slot-asterisk" aria-hidden="true">*</span>
                      ) : null}
                    </button>
                  )
                })}
              </div>
              <div className="arrange-toolbar-right">
                <IconBtn
                  icon={<IconZoomOut />}
                  title={`Smaller thumbnails (now ${Math.round(arrangeZoom * 100)}%)`}
                  label="Zoom out"
                  onClick={() => nudgeArrangeZoom(-0.1)}
                />
                <IconBtn
                  icon={<IconZoomIn />}
                  title={`Larger thumbnails (now ${Math.round(arrangeZoom * 100)}%)`}
                  label="Zoom in"
                  onClick={() => nudgeArrangeZoom(0.1)}
                />
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

      {tab !== 'arrange' && (
        <NavDots session={session} onGo={async (idx) => { try { await goTo(idx) } catch (err) { setError(err.message) } }} />
      )}

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
          <Hotkey
            kbd="Del"
            label={img?.media_kind === 'video' ? 'Clear KFs' : 'Clear'}
            danger
            onClick={async () => { try { apply(await api.clearFocal(session.current_idx)) } catch (err) { setError(err.message) } }}
          />
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
            {img?.media_kind === 'video' && (
              <Hotkey
                kbd="Space"
                label="Play/Pause"
                onClick={() => previewCompareRef.current?.togglePlay?.()}
              />
            )}
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
              label="Prev overlay"
              onClick={() => previewCompareRef.current?.stepNeighbor?.(-0.1)}
            />
            <Hotkey
              kbd=">"
              label="Next overlay"
              onClick={() => previewCompareRef.current?.stepNeighbor?.(0.1)}
            />
          </>
        )}
        {tab === 'arrange' && (
          <Hotkey
            kbd="⌫"
            label="Clear slot"
            danger
            disabled={(session.arrangement_active || 'original') === 'original'}
            onClick={() => openClearSlot(session.arrangement_active)}
          />
        )}
        <Hotkey kbd="R" label="Reset" danger onClick={() => setResetOpen(true)} />
        <Hotkey kbd="E" label="Export" onClick={() => setExportOpen(true)} />
        <Hotkey kbd="Esc" label={batchMode ? 'Next folder' : 'Opener'} onClick={onFinished} />
      </div>

      {clearSlotOpen && (
        <div className="export-overlay" onClick={() => !clearingSlot && (setClearSlotOpen(false), setClearSlotTarget(null))}>
          <div className="export-card card" onClick={(e) => e.stopPropagation()}>
            <h2>Clear arrangement slot?</h2>
            <p className="muted">
              Removes slot {clearSlotTarget || session.arrangement_active || ''} and restores the Original order.
              This cannot be undone.
            </p>
            <div className="row" style={{ marginTop: 16 }}>
              <button className="danger" disabled={clearingSlot} onClick={confirmClearSlot}>
                {clearingSlot ? 'Clearing…' : 'Clear slot'}
              </button>
              <button
                className="secondary"
                disabled={clearingSlot}
                onClick={() => { setClearSlotOpen(false); setClearSlotTarget(null) }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

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
