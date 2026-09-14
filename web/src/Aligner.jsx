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

function focalFromImage(img, pending) {
  if (pending) return pending
  return img.focal
    ? { x: img.focal[0], y: img.focal[1] }
    : { x: img.width / 2, y: img.height / 2 }
}

function SortableThumb({ id, img, selected, onSelect, onOpen }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.45 : 1 }
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`thumb ${selected ? 'selected' : ''} ${img.completed ? 'done' : ''}`}
      onClick={() => onSelect(img.id)}
      onDoubleClick={() => onOpen(img.id)}
      {...attributes}
      {...listeners}
    >
      <img src={mediaUrl('thumb', img.id, `?n=${encodeURIComponent(img.filename)}`)} alt={img.filename} loading="lazy" />
      <span className="idx">{img.id + 1}</span>
    </div>
  )
}

const PAGE_SIZE = 21

function NavDots({ session, onGo }) {
  const total = session.total
  const current = session.current_idx
  const page = Math.floor(current / PAGE_SIZE)
  const start = page * PAGE_SIZE
  const count = Math.min(PAGE_SIZE, total - start)
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  return (
    <div className="nav-dots" role="navigation" aria-label="Images">
      <div className="dot-row">
        {Array.from({ length: count }, (_, i) => {
          const idx = start + i
          const im = session.images[idx]
          const cls = [
            'dot',
            idx === current ? 'current' : '',
            im?.completed ? 'done' : '',
          ].filter(Boolean).join(' ')
          return (
            <button
              key={im?.filename || idx}
              type="button"
              className={cls}
              title={`${idx + 1}. ${im?.filename || ''}`}
              onClick={() => onGo(idx)}
            />
          )
        })}
      </div>
      {pages > 1 && (
        <div className="dot-pages">
          {Array.from({ length: pages }, (_, p) => (
            <button
              key={p}
              type="button"
              className={`page-dot ${p === page ? 'current' : ''}`}
              title={`Page ${p + 1}`}
              onClick={() => onGo(p * PAGE_SIZE)}
            />
          ))}
        </div>
      )}
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

function FocalStage({ session, pending, setPending, onConfirm }) {
  const canvasRef = useRef(null)
  const imgRef = useRef(null)
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
    if (!img || !canvas || !image || !image.naturalWidth) return
    const parent = canvas.parentElement
    const maxW = parent.clientWidth
    const maxH = parent.clientHeight
    const scale = Math.min(maxW / image.naturalWidth, maxH / image.naturalHeight)
    const dw = Math.max(1, Math.round(image.naturalWidth * scale))
    const dh = Math.max(1, Math.round(image.naturalHeight * scale))
    canvas.width = dw
    canvas.height = dh
    canvas.style.width = `${dw}px`
    canvas.style.height = `${dh}px`
    const ctx = canvas.getContext('2d')
    ctx.drawImage(image, 0, 0, dw, dh)
    if (!pending && !img.focal) return
    const { origW, origH } = sourceSize()
    const fx = (focal.x / origW) * dw
    const fy = (focal.y / origH) * dh
    ctx.strokeStyle = '#e74c3c'
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

  useEffect(() => {
    draw()
    const onResize = () => draw()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [session.current_idx, pending, img?.id, img?.focal, img?.width, img?.height])

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

  if (!img) return null

  return (
    <div className="stage">
      <img
        ref={imgRef}
        className="full"
        src={mediaUrl('original', img.id, `?n=${encodeURIComponent(img.filename)}`)}
        alt=""
        style={{ display: 'none' }}
        onLoad={draw}
      />
      <canvas
        ref={canvasRef}
        onClick={(e) => setPending(toOrig(e))}
        onDoubleClick={(e) => {
          const pt = toOrig(e)
          setPending(pt)
          onConfirm(pt)
        }}
        onContextMenu={(e) => {
          e.preventDefault()
          const { origW, origH } = sourceSize()
          setPending({ x: origW / 2, y: origH / 2 })
        }}
      />
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
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }))

  const ids = useMemo(() => session.images.map((im) => im.filename), [session])

  const apply = (next) => {
    setSession(next)
    setPending(null)
  }

  const savePending = async () => {
    if (!pending) return session
    const next = await api.setFocal({ x: pending.x, y: pending.y, index: session.current_idx })
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
    await api.setFocal({ x: pt.x, y: pt.y, index: session.current_idx })
    apply(await api.confirm())
    return null
  }

  const discardCurrent = async () => {
    const next = await api.discard(session.current_idx)
    if (next.empty) onFinished()
    else apply(next)
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
        <div className="workspace">
          <div className="side-thumb">
            {prev && <img src={mediaUrl('thumb', prev.id, `?n=${encodeURIComponent(prev.filename)}`)} alt="" />}
          </div>
          <FocalStage
            session={session}
            pending={pending}
            setPending={setPending}
            onConfirm={confirmPt}
          />
          <div className="side-thumb">
            {nextImg && <img src={mediaUrl('thumb', nextImg.id, `?n=${encodeURIComponent(nextImg.filename)}`)} alt="" />}
          </div>
        </div>
      )}

      {tab === 'preview' && img && (
        <div className="workspace preview">
          <div className="stage">
            <img
              className="full"
              src={mediaUrl('preview', img.id, `?orientation=${session.alignment_mode || 'landscape'}&f=${img.focal?.[0] ?? 0}-${img.focal?.[1] ?? 0}&n=${encodeURIComponent(img.filename)}`)}
              alt="preview"
            />
          </div>
        </div>
      )}

      {tab === 'arrange' && (
        <div className="workspace arrange">
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={ids} strategy={rectSortingStrategy}>
              <div className="grid">
                {session.images.map((im) => (
                  <SortableThumb
                    key={im.filename}
                    id={im.filename}
                    img={im}
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
        <Hotkey kbd="X" label="Discard" danger onClick={() => discardCurrent().catch((err) => setError(err.message))} />
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
