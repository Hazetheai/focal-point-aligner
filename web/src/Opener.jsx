import { useEffect, useRef, useState } from 'react'
import { api, pickFolder } from './api.js'

export default function Opener({ onStart, onBatchSession }) {
  const [mode, setMode] = useState('single')
  const [input, setInput] = useState('')
  const [output, setOutput] = useState('')
  const [width, setWidth] = useState(2560)
  const [height, setHeight] = useState(1440)
  const [batchRoot, setBatchRoot] = useState('')
  const [queue, setQueue] = useState([])
  const [selected, setSelected] = useState([])
  const [mergeName, setMergeName] = useState('merged')
  const [deleteSources, setDeleteSources] = useState(false)
  const [useAligned, setUseAligned] = useState(true)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)
  const dropRef = useRef(null)
  const loadedRoot = useRef('')

  useEffect(() => {
    api.prefs().then((p) => {
      setInput(p.last_input_dir || '')
      setOutput(p.last_output_dir || '')
      setWidth(p.target_width || 2560)
      setHeight(p.target_height || 1440)
      const nextMode = p.mode || 'single'
      setMode(nextMode)
      const root = p.last_batch_root_dir || ''
      setBatchRoot(root)
      if (nextMode === 'batch' && root) loadBatch(root)
    }).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function browse(setter, title, { after } = {}) {
    setError('')
    try {
      const path = await pickFolder(title)
      if (!path) return
      setter(path)
      if (after) after(path)
    } catch (e) {
      setError(e.message || 'Folder picker failed')
    }
  }

  function onPickInput(path) {
    setInput(path)
    setOutput((cur) => {
      if (cur) return cur
      const parts = path.replace(/\/$/, '').split('/')
      const name = parts.pop() || 'images'
      const parent = parts.join('/') || '/'
      return `${parent}/${name}_aligned`
    })
  }

  async function startSingle() {
    setError('')
    setInfo('')
    setBusy(true)
    try {
      const session = await api.openSession({
        input_folder: input,
        output_folder: output || undefined,
        target_width: Number(width),
        target_height: Number(height),
      })
      await api.savePrefs({ mode: 'single' })
      onStart(session, { mode: 'single' })
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function loadBatch(root = batchRoot) {
    if (!root) {
      setError('Choose a batch root folder first')
      return
    }
    setError('')
    setInfo('')
    setBusy(true)
    try {
      const data = await api.openBatch(root)
      const next = data.queue || []
      setQueue(next)
      setSelected([])
      loadedRoot.current = root
      if (!next.length) setInfo('No image-bearing folders found in this root')
    } catch (e) {
      setError(e.message)
      setQueue([])
    } finally {
      setBusy(false)
    }
  }

  async function startBatch() {
    setError('')
    setInfo('')
    setBusy(true)
    try {
      await api.savePrefs({
        mode: 'batch',
        target_width: Number(width),
        target_height: Number(height),
      })
      if (!queue.length) await loadBatch()
      const nxt = await api.batchNext()
      if (nxt.done) {
        setError('No pending folders in this batch')
        return
      }
      onBatchSession(nxt.session, nxt.folder)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function doMerge() {
    if (selected.length < 1) return
    const sources = selected
    const parent = sources[0].replace(/\/[^/]+$/, '')
    const dest = `${parent}/${mergeName.trim() || 'merged'}`
    setBusy(true)
    setError('')
    setInfo('')
    try {
      const report = await api.merge({
        sources,
        dest,
        use_aligned: useAligned,
        delete_sources: deleteSources,
      })
      setInfo(`Merged ${report.merged_count} files → ${report.dest}`)
      await loadBatch()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function doMove() {
    setBusy(true)
    setError('')
    setInfo('')
    try {
      const report = await api.moveAligned(batchRoot)
      const n = Array.isArray(report.moved) ? report.moved.length : 0
      setInfo(n ? `Moved ${n} aligned folder(s) → ${report.dest}` : 'No aligned output folders found to move')
      await loadBatch()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  function toggleSelected(path) {
    setSelected((cur) => cur.includes(path) ? cur.filter((x) => x !== path) : [...cur, path])
  }

  function onDrop(ev) {
    ev.preventDefault()
    const f = ev.dataTransfer.files?.[0]
    if (f?.path) {
      const dir = f.path.replace(/\/[^/]+$/, '')
      if (mode === 'batch') {
        setBatchRoot(dir)
        loadBatch(dir)
      } else {
        onPickInput(dir)
      }
    }
  }

  return (
    <div className="screen" ref={dropRef} onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <h1>Focal Point Aligner</h1>
      <p className="muted">Pick a local folder. Browse opens a folder picker — files cannot be selected.</p>

      <div className="row">
        <button className={mode === 'single' ? '' : 'secondary'} onClick={() => setMode('single')}>Single</button>
        <button className={mode === 'batch' ? '' : 'secondary'} onClick={() => setMode('batch')}>Batch</button>
      </div>

      <div className="card row">
        <label>Width <input type="number" value={width} onChange={(e) => setWidth(e.target.value)} /></label>
        <label>Height <input type="number" value={height} onChange={(e) => setHeight(e.target.value)} /></label>
      </div>

      {mode === 'single' ? (
        <div className="card">
          <div className="row">
            <input className="grow" placeholder="Input folder" value={input} onChange={(e) => setInput(e.target.value)} />
            <button className="secondary" type="button" onClick={() => browse(onPickInput, 'Select input folder')}>Browse</button>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <input className="grow" placeholder="Output folder (optional)" value={output} onChange={(e) => setOutput(e.target.value)} />
            <button className="secondary" type="button" onClick={() => browse(setOutput, 'Select output folder')}>Browse</button>
          </div>
          <div className="row" style={{ marginTop: 16 }}>
            <button disabled={busy || !input} onClick={startSingle}>Start</button>
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="row">
            <input className="grow" placeholder="Batch root folder" value={batchRoot} onChange={(e) => setBatchRoot(e.target.value)} />
            <button
              className="secondary"
              type="button"
              onClick={() => browse(setBatchRoot, 'Select batch root folder', { after: (path) => loadBatch(path) })}
            >
              Browse
            </button>
            <button className="secondary" type="button" disabled={busy || !batchRoot} onClick={() => loadBatch()}>Refresh list</button>
          </div>
          <ul className="queue">
            {queue.map((item) => (
              <li key={item.path}>
                <label>
                  <input
                    type="checkbox"
                    checked={selected.includes(item.path)}
                    onChange={() => toggleSelected(item.path)}
                  />
                  {' '}{item.name}
                </label>
                <span className="muted">{item.done ? 'done' : 'pending'}</span>
              </li>
            ))}
          </ul>
          <div className="row" style={{ marginTop: 12 }}>
            <button disabled={busy || !batchRoot} onClick={startBatch}>Start Batch</button>
            <input value={mergeName} onChange={(e) => setMergeName(e.target.value)} placeholder="Merged folder name" />
            <label className="muted"><input type="checkbox" checked={useAligned} onChange={(e) => setUseAligned(e.target.checked)} /> Use aligned</label>
            <label className="muted"><input type="checkbox" checked={deleteSources} onChange={(e) => setDeleteSources(e.target.checked)} /> Delete sources</label>
            <button className="secondary" type="button" disabled={busy || selected.length < 1} onClick={doMerge}>Merge selected</button>
            <button className="secondary" type="button" disabled={busy || !batchRoot} onClick={doMove}>Move aligned</button>
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}
      {info && <p className="ok">{info}</p>}
    </div>
  )
}
