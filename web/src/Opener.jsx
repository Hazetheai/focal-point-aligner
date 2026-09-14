import { useEffect, useRef, useState } from 'react'
import { api, pickFolder } from './api.js'

export default function Opener({ onStart, onBatchSession }) {
  const [prefs, setPrefs] = useState({})
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
  const [busy, setBusy] = useState(false)
  const dropRef = useRef(null)

  useEffect(() => {
    api.prefs().then((p) => {
      setPrefs(p)
      setInput(p.last_input_dir || '')
      setOutput(p.last_output_dir || '')
      setWidth(p.target_width || 2560)
      setHeight(p.target_height || 1440)
      setMode(p.mode || 'single')
      setBatchRoot(p.last_batch_root_dir || '')
    }).catch(() => {})
  }, [])

  async function browse(setter) {
    const path = await pickFolder()
    if (path) setter(path)
  }

  async function startSingle() {
    setError('')
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

  async function loadBatch() {
    setError('')
    setBusy(true)
    try {
      const data = await api.openBatch(batchRoot)
      setQueue(data.queue || [])
      setSelected([])
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function startBatch() {
    setError('')
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
    const sources = selected.map((i) => queue[i].path)
    const parent = sources[0].replace(/\/[^/]+$/, '')
    const dest = `${parent}/${mergeName}`
    setBusy(true)
    setError('')
    try {
      const report = await api.merge({
        sources,
        dest,
        use_aligned: useAligned,
        delete_sources: deleteSources,
      })
      setError(`Merged ${report.merged_count} files → ${report.dest}`)
      await loadBatch()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function doMove() {
    setBusy(true)
    try {
      const report = await api.moveAligned(batchRoot)
      setError(`Moved ${report.moved ?? JSON.stringify(report)}`)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  function onDrop(ev) {
    ev.preventDefault()
    const f = ev.dataTransfer.files?.[0]
    if (f?.path) {
      const dir = f.path.replace(/\/[^/]+$/, '')
      if (mode === 'batch') setBatchRoot(dir)
      else setInput(dir)
    }
  }

  return (
    <div className="screen" ref={dropRef} onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <h1>Focal Point Aligner</h1>
      <p className="muted">Pick a local folder. Images stay on disk; Python only aligns.</p>

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
            <button className="secondary" onClick={() => browse(setInput)}>Browse</button>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <input className="grow" placeholder="Output folder (optional)" value={output} onChange={(e) => setOutput(e.target.value)} />
            <button className="secondary" onClick={() => browse(setOutput)}>Browse</button>
          </div>
          <div className="row" style={{ marginTop: 16 }}>
            <button disabled={busy || !input} onClick={startSingle}>Start</button>
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="row">
            <input className="grow" placeholder="Batch root folder" value={batchRoot} onChange={(e) => setBatchRoot(e.target.value)} />
            <button className="secondary" onClick={() => browse(setBatchRoot)}>Browse</button>
            <button className="secondary" disabled={busy || !batchRoot} onClick={loadBatch}>Refresh list</button>
          </div>
          <ul className="queue">
            {queue.map((item, i) => (
              <li key={item.path}>
                <label>
                  <input
                    type="checkbox"
                    checked={selected.includes(i)}
                    onChange={(e) => {
                      setSelected((cur) => e.target.checked ? [...cur, i] : cur.filter((x) => x !== i))
                    }}
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
            <button className="secondary" disabled={busy || selected.length < 1} onClick={doMerge}>Merge selected</button>
            <button className="secondary" disabled={busy || !batchRoot} onClick={doMove}>Move aligned</button>
          </div>
        </div>
      )}

      {error && <p className={error.startsWith('Merged') ? 'ok' : 'error'}>{error}</p>}
      <p className="muted">In the browser, paste an absolute folder path. The desktop app Browse dialog is native.</p>
    </div>
  )
}
