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
import { api, mediaUrl } from './api.js'
import { computeCrop, cropToWidget, targetForMode } from './crop.js'

const PAGE_SIZE = 10
const COLS_KEY = 'fpa-original-cols'
const DEFAULT_COLS = [16, 68, 16]
const RIGHT_DOUBLE_MS = 400

function focalFromImage(img, pending) {
  if (pending) return pending
  return img.focal
    ? { x: img.focal[0], y: img.focal[1], autoCenter: Boolean(img.auto_center || img.focal_at_center) }
    : { x: img.width / 2, y: img.height / 2, autoCenter: true }
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

function SortableThumb({ id, img, selected, onSelect, onOpen, view, orientation }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.45 : 1 }
  const aligned = view === 'aligned'
  const src = aligned && img.focal
    ? mediaUrl('preview', img.id, `?orientation=${orientation || 'landscape'}&f=${img.focal[0]}-${img.focal[1]}&n=${encodeURIComponent(img.filename)}`)
    : mediaUrl('thumb', img.id, `?n=${encodeURIComponent(img.filename)}`)
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`thumb ${selected ? 'selected' : ''} ${img.completed ? 'done' : ''} ${aligned && !img.focal ? 'no-focal' : ''}`}
      onClick={() => onSelect(img.id)}
      onDoubleClick={() => onOpen(img.id)}
      {...attributes}
      {...listeners}
    >
      <img src={src} alt={img.filename} loading="lazy" draggable={false} />
      <span className="idx">{img.id + 1}</span>
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

function Hotkey({ kbd, label, onClick, danger }) {
  return (
    <button type="button" className={`hotkey ${danger ? 'danger' : ''}`} onClick={onClick} title={`${label} (${kbd})`}>
      <span className="hotkey-kbd">{kbd}</span>
      <span className="hotkey-label">{label}</span>
    </button>
  )
}

function ImageFacts({ img, pending }) {
  const [open, setOpen] = useState(false)
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
    <div className="image-facts">
      <button type="button" className="facts-toggle" onClick={toggleOpen} aria-expanded={open}>
        <span>{img.width} × {img.height} px</span>
        <span>{mp ? `${Number(mp).toFixed(1)} MP` : ''}</span>
        {dpi && <span>{dpi}</span>}
        <span className="facts-caret">{open ? 'Hide' : 'Details'}</span>
      </button>
      {open && (
        <dl className="facts-panel">
          <div><dt>File</dt><dd>{img.filename}</dd></div>
          <div><dt>Pixels</dt><dd>{img.width.toLocaleString()} × {img.height.toLocaleString()} ({Number(mp).toFixed(2)} MP)</dd></div>
          <div><dt>DPI</dt><dd>{dpi || 'not tagged'}</dd></div>
          <div><dt>Size</dt><dd>{formatBytes(img.bytes)}</dd></div>
          <div><dt>Format</dt><dd>{(img.format || '—').toUpperCase()}{img.mode ? ` · ${img.mode}` : ''}</dd></div>
          <div><dt>EXIF orientation</dt><dd>{img.orientation || 1}</dd></div>
          <div><dt>Focal</dt><dd>{focal ? `${Math.round(focal.x)}, ${Math.round(focal.y)}${pending ? ' (pending)' : ''}` : 'not set'}</dd></div>
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
  return (
    <button type="button" className="side-thumb" onClick={onOpen} title={`Go to ${img.filename}`}>
      <span className="side-label">{label}</span>
      <span className="side-frame">
        <img src={mediaUrl('original', img.id, `?n=${encodeURIComponent(img.filename)}`)} alt={img.filename} />
      </span>
      <span className="side-name">{img.filename}</span>
    </button>
  )
}

function FocalStage({ session, pending, setPending, onConfirm, onDiscard }) {
  const canvasRef = useRef(null)
  const imgRef = useRef(null)
  const stageRef = useRef(null)
  const lastRight = useRef(0)
  const drawLatest = useRef(() => {})
  const img = session.images[session.current_idx]
  const focal = img ? focalFromImage(img, pending) : { x: 0, y: 0 }

  function sourceSize() {
    const image = imgRef.current
    const srcW = image?.naturalWidth || 0
    const srcH = image?.naturalHeight || 0
    return {
      origW: srcW || img?.width || 1,
      origH: srcH || img?.height || 1,
    }
  }

  function draw() {
    const canvas = canvasRef.current
    const image = imgRef.current
    if (!img || !canvas || !image) return
    const ready = image.complete && image.naturalWidth > 0
    const dw = ready ? Math.max(1, Math.round(image.clientWidth)) : 0
    const dh = ready ? Math.max(1, Math.round(image.clientHeight)) : 0
    canvas.width = dw
    canvas.height = dh
    if (!dw || !dh) return
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, dw, dh)
    const showOverlay = Boolean(pending || img.focal)
    if (!showOverlay) return
    const { origW, origH } = sourceSize()
    const fx = (focal.x / origW) * dw
    const fy = (focal.y / origH) * dh
    const target = targetForMode(session)
    const crop = computeCrop(focal.x, focal.y, origW, origH, target.w, target.h)
    const box = cropToWidget(crop.x, crop.y, crop.w, crop.h, dw, dh, origW, origH)
    ctx.save()
    ctx.fillStyle = 'rgba(8, 8, 14, 0.55)'
    ctx.beginPath()
    ctx.rect(0, 0, dw, dh)
    ctx.rect(box.x, box.y, box.w, box.h)
    ctx.fill('evenodd')
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.95)'
    ctx.lineWidth = 2
    ctx.strokeRect(box.x + 1, box.y + 1, Math.max(0, box.w - 2), Math.max(0, box.h - 2))
    ctx.restore()
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
    if (!stage) return undefined
    const ro = new ResizeObserver(redraw)
    ro.observe(stage)
    if (image) ro.observe(image)
    window.addEventListener('resize', redraw)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', redraw)
    }
  }, [img?.id, img?.filename])

  function toOrig(ev) {
    const canvas = canvasRef.current
    if (!canvas || !img) return { x: 0, y: 0 }
    const rect = canvas.getBoundingClientRect()
    if (!rect.width || !rect.height) return { x: 0, y: 0 }
    const { origW, origH } = sourceSize()
    const nx = (ev.clientX - rect.left) / rect.width
    const ny = (ev.clientY - rect.top) / rect.height
    return {
      x: Math.max(0, Math.min(origW, nx * origW)),
      y: Math.max(0, Math.min(origH, ny * origH)),
    }
  }

  function centerPending() {
    const { origW, origH } = sourceSize()
    return { x: origW / 2, y: origH / 2, autoCenter: true }
  }

  if (!img) return null

  const pointerHandlers = {
    onClick: (e) => {
      if (e.button !== 0) return
      setPending(toOrig(e))
    },
    onDoubleClick: (e) => {
      if (e.button !== 0) return
      const pt = toOrig(e)
      setPending(pt)
      onConfirm(pt)
    },
    onContextMenu: (e) => e.preventDefault(),
    onMouseDown: (e) => {
      if (e.button === 1) {
        e.preventDefault()
        e.stopPropagation()
        onDiscard()
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
      }
    },
    onPointerDown: (e) => {
      if (e.button === 1) e.preventDefault()
    },
  }

  return (
    <div className="stage" ref={stageRef}>
      <div className="stage-photo">
        <img
          ref={imgRef}
          className="full"
          src={mediaUrl('original', img.id, `?n=${encodeURIComponent(img.filename)}`)}
          alt=""
          draggable={false}
          onLoad={() => drawLatest.current()}
        />
        <canvas ref={canvasRef} className="stage-overlay" {...pointerHandlers} />
      </div>
    </div>
  )
}

export default function Aligner({ session, setSession, batchMode, onFinished }) {
  const [tab, setTab] = useState('original')
  const [pending, setPending] = useState(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [progress, setProgress] = useState(null)
  const [error, setError] = useState('')
  const [cols, setCols] = useColumnLayout()
  const [arrangeView, setArrangeView] = useState('original')
  const workspaceRef = useRef(null)
  const colsRef = useRef(cols)
  const dragOrigin = useRef(cols)
  const discarding = useRef(false)
  colsRef.current = cols
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }))

  const ids = useMemo(() => session.images.map((im) => im.filename), [session])

  const apply = (next) => {
    setSession(next)
    setPending(null)
  }

  const savePending = async () => {
    if (!pending) return session
    const next = await api.setFocal({
      x: pending.x,
      y: pending.y,
      auto_center: Boolean(pending.autoCenter),
      index: session.current_idx,
    })
    setPending(null)
    setSession(next)
    return next
  }

  const switchTab = async (nextTab) => {
    if (nextTab === tab) return
    try {
      if (tab === 'original' && pending) await savePending()
      setTab(nextTab)
    } catch (err) {
      setError(err.message)
    }
  }

  const goTo = async (index, { wrap = false } = {}) => {
    if (index === session.current_idx) return
    apply(await api.navigate({ index, wrap }))
  }

  const step = async (direction) => {
    const atStart = session.current_idx <= 0 && direction < 0
    const atEnd = session.current_idx >= session.total - 1 && direction > 0
    if (atStart || atEnd) return
    apply(await api.navigate({ direction, wrap: false }))
  }

  const confirmPt = async (pt) => {
    await api.setFocal({
      x: pt.x,
      y: pt.y,
      auto_center: Boolean(pt.autoCenter),
      index: session.current_idx,
    })
    apply(await api.confirm())
    return null
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

  const onKey = useCallback(async (e) => {
    if (exportOpen) return
    if (e.target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return
    const k = e.key
    try {
      if (k === 'Enter') {
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
      else if (k === 'Delete' || k === 'Backspace') apply(await api.clearFocal(session.current_idx))
      else if (k === 'p' || k === 'P') await switchTab(tab === 'preview' ? 'original' : 'preview')
      else if (k === 'o' || k === 'O') {
        const mode = session.alignment_mode === 'portrait' ? 'landscape' : 'portrait'
        apply(await api.setMode(mode))
      } else if (k === 'a' || k === 'A') await switchTab(tab === 'arrange' ? 'original' : 'arrange')
      else if (k === '[') apply(await api.shift(-1))
      else if (k === ']') apply(await api.shift(1))
      else if (k === 'r' || k === 'R') apply(await api.reset())
      else if (k === 'f' || k === 'F') setExportOpen(true)
      else if (k === 'Escape') onFinished()
    } catch (err) {
      setError(err.message)
    }
  }, [session, pending, tab, exportOpen, onFinished])

  useEffect(() => {
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onKey])

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

  async function onDragEnd(event) {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = session.images.findIndex((im) => im.filename === active.id)
    const newIndex = session.images.findIndex((im) => im.filename === over.id)
    if (oldIndex < 0 || newIndex < 0) return
    const order = arrayMove(session.images.map((_, i) => i), oldIndex, newIndex)
    const currentName = session.images[session.current_idx]?.filename
    const optimistic = arrayMove(session.images, oldIndex, newIndex).map((im, i) => ({ ...im, id: i }))
    const newCurrent = Math.max(0, optimistic.findIndex((im) => im.filename === currentName))
    setSession({ ...session, images: optimistic, current_idx: newCurrent })
    try {
      apply(await api.order(order))
    } catch (err) {
      setError(err.message)
      apply(await api.session())
    }
  }

  async function runExport(orientation) {
    setExporting(true)
    setError('')
    try {
      const res = await api.export({
        output_folder: session.output_folder,
        orientation,
        cleanup: true,
      })
      const text = await res.text()
      const lines = text.split('\n').filter((l) => l.startsWith('data: '))
      const last = lines.length ? JSON.parse(lines[lines.length - 1].slice(6)) : {}
      setProgress(last)
      setTimeout(() => onFinished(), 400)
    } catch (e) {
      setError(e.message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="screen">
      <div className="header-bar">
        <div className="header-meta">
          <h2>{img?.filename}</h2>
          <div className="status">
            {session.current_idx + 1}/{session.total} · {session.alignment_mode}
          </div>
          <ImageFacts img={img} pending={pending} />
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
        <div className="row">
          <button className="secondary" onClick={() => setExportOpen(true)}>Export (F)</button>
          <button className="secondary" onClick={onFinished}>Done</button>
        </div>
      </div>

      {tab === 'original' && (
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
          />
          <SplitHandle onBegin={() => { dragOrigin.current = colsRef.current }} onDrag={(dx) => dragSplit('right', dx)} />
          <SidePane img={nextImg} label="Next" onOpen={() => goTo(session.current_idx + 1)} />
        </div>
      )}

      {tab === 'preview' && img && (
        <div className="workspace preview">
          <div className="stage">
            <img
              className="full"
              src={img.focal
                ? mediaUrl('preview', img.id, `?orientation=${session.alignment_mode || 'landscape'}&f=${img.focal[0]}-${img.focal[1]}&n=${encodeURIComponent(img.filename)}`)
                : mediaUrl('original', img.id, `?n=${encodeURIComponent(img.filename)}`)}
              alt="preview"
            />
            {!img.focal && <span className="stage-note">No focal — showing original</span>}
          </div>
        </div>
      )}

      {tab === 'arrange' && (
        <div className="workspace arrange">
          <div className="arrange-toolbar">
            <button type="button" aria-selected={arrangeView === 'original'} onClick={() => setArrangeView('original')}>Original</button>
            <button type="button" aria-selected={arrangeView === 'aligned'} onClick={() => setArrangeView('aligned')}>Aligned</button>
            <span className="muted">{arrangeView === 'original' ? 'Before focal crop' : 'After aligned crop'}</span>
          </div>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={ids} strategy={rectSortingStrategy}>
              <div className="grid">
                {session.images.map((im) => (
                  <SortableThumb
                    key={im.filename}
                    id={im.filename}
                    img={im}
                    view={arrangeView}
                    orientation={session.alignment_mode}
                    selected={im.id === session.current_idx}
                    onSelect={async (id) => apply(await api.navigate({ index: id }))}
                    onOpen={async (id) => {
                      apply(await api.navigate({ index: id }))
                      setTab('original')
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
        <Hotkey kbd="Enter" label="Save" onClick={async () => { try { await confirmPt(focalFromImage(img, pending)) } catch (err) { setError(err.message) } }} />
        <Hotkey kbd="Space" label="Skip" onClick={() => step(1)} />
        <Hotkey kbd="X / MMB" label="Discard" danger onClick={() => discardCurrent().catch((err) => setError(err.message))} />
        <Hotkey kbd="Del" label="Clear" onClick={async () => { try { apply(await api.clearFocal(session.current_idx)) } catch (err) { setError(err.message) } }} />
        <Hotkey kbd="P" label="Preview" onClick={() => switchTab(tab === 'preview' ? 'original' : 'preview')} />
        <Hotkey kbd="O" label="Orient" onClick={async () => { try { apply(await api.setMode(session.alignment_mode === 'portrait' ? 'landscape' : 'portrait')) } catch (err) { setError(err.message) } }} />
        <Hotkey kbd="A" label="Arrange" onClick={() => switchTab(tab === 'arrange' ? 'original' : 'arrange')} />
        <Hotkey kbd="[ ]" label="Reorder" onClick={async () => { try { apply(await api.shift(1)) } catch (err) { setError(err.message) } }} />
        <Hotkey kbd="F" label="Export" onClick={() => setExportOpen(true)} />
        <Hotkey kbd="Esc" label={batchMode ? 'Next folder' : 'Opener'} onClick={onFinished} />
      </div>

      {exportOpen && (
        <div className="export-overlay" onClick={() => !exporting && setExportOpen(false)}>
          <div className="export-card card" onClick={(e) => e.stopPropagation()}>
            <h2>Export aligned images</h2>
            <p className="muted">{session.completed_count}/{session.total} have focals → {session.output_folder}</p>
            <div className="row" style={{ marginTop: 16 }}>
              <button disabled={exporting} onClick={() => runExport('landscape')}>Landscape</button>
              <button disabled={exporting} className="secondary" onClick={() => runExport('portrait')}>Portrait</button>
            </div>
            {progress && (
              <div style={{ marginTop: 16 }}>
                <div className="progress"><div style={{ width: `${(100 * (progress.done || 0)) / (progress.total || 1)}%` }} /></div>
                <p className="muted">{progress.exported ?? progress.done} written</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
