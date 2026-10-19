import { useEffect, useMemo, useRef, useState } from 'react'
import { api, pickFile, pickFolder, readSse } from './api.js'
import { SIZE_RATIOS, matchRatio, sizeLabel } from './presets.js'

function SizePresets({ width, height, onChange }) {
  const ratioId = matchRatio(width, height)
  const activeRatio = SIZE_RATIOS.find((r) => r.id === ratioId) || SIZE_RATIOS[0]
  const matchedSize = activeRatio.sizes.find(([w, h]) => w === Number(width) && h === Number(height))

  return (
    <div className="size-presets">
      <div className="row wrap">
        {SIZE_RATIOS.map((r) => (
          <button
            key={r.id}
            type="button"
            className={ratioId === r.id ? '' : 'secondary'}
            onClick={() => {
              const [w, h] = r.sizes[Math.min(1, r.sizes.length - 1)]
              onChange(w, h)
            }}
          >
            {r.label}
          </button>
        ))}
      </div>
      <div className="row wrap" style={{ marginTop: 8 }}>
        {(SIZE_RATIOS.find((r) => r.id === ratioId) || activeRatio).sizes.map(([w, h]) => (
          <button
            key={`${w}x${h}`}
            type="button"
            className={matchedSize && w === Number(width) && h === Number(height) ? '' : 'secondary'}
            onClick={() => onChange(w, h)}
          >
            {sizeLabel([w, h])}
          </button>
        ))}
      </div>
    </div>
  )
}

export default function Opener({ onStart, onBatchSession, theme = 'dark', onToggleTheme, onOpenHelp }) {
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
  const [importDest, setImportDest] = useState('')
  const [importName, setImportName] = useState('imported')
  const [importPrefix, setImportPrefix] = useState('image_urls--')
  const [importSuffix, setImportSuffix] = useState('')
  const [importFolderTemplate, setImportFolderTemplate] = useState('{name}')
  const [importUrls, setImportUrls] = useState('')
  const [importFile, setImportFile] = useState('')
  const [importFolder, setImportFolder] = useState('')
  const [importProgress, setImportProgress] = useState(null)
  const [importLog, setImportLog] = useState([])
  const dropRef = useRef(null)
  const loadedRoot = useRef('')

  const urlCount = useMemo(
    () => importUrls.split(/\n/).map((l) => l.trim()).filter((l) => /^https?:\/\//i.test(l)).length,
    [importUrls],
  )

  const importNamePattern = useMemo(
    () => `${importPrefix}{name}${importSuffix}`,
    [importPrefix, importSuffix],
  )

  const importNameExample = useMemo(() => {
    const sample = 'cats'
    const fileStem = importNamePattern.replace('{name}', sample)
    const folder = importFolderTemplate
      .replace('{name}', sample)
      .replace('{nn}', '01')
      .replace('{n}', '1')
      .replace('{stem}', fileStem)
    return `${fileStem}.txt → ${folder}/`
  }, [importNamePattern, importFolderTemplate])

  const FOLDER_TOKENS = [
    { token: '{name}', tip: 'Name captured from the list filename' },
    { token: '{n}', tip: '1-based index among lists (1, 2, 3…)' },
    { token: '{nn}', tip: 'Zero-padded index (01, 02, 03…)' },
    { token: '{stem}', tip: 'Full list filename without .txt' },
  ]

  function insertFolderToken(token) {
    setImportFolderTemplate((cur) => `${cur || ''}${token}`)
  }

  useEffect(() => {
    api.prefs().then((p) => {
      setInput(p.last_input_dir || '')
      setOutput(p.last_output_dir || '')
      setWidth(p.target_width || 2560)
      setHeight(p.target_height || 1440)
      const nextMode = p.mode || 'single'
      setMode(nextMode === 'import' ? 'import' : nextMode)
      const root = p.last_batch_root_dir || ''
      setBatchRoot(root)
      setImportDest(root || '')
      const pat = (p.import_name_pattern || 'image_urls--{name}').trim() || 'image_urls--{name}'
      const token = '{name}'
      const idx = pat.indexOf(token)
      if (idx >= 0) {
        setImportPrefix(pat.slice(0, idx))
        setImportSuffix(pat.slice(idx + token.length))
      } else {
        setImportPrefix(pat)
        setImportSuffix('')
      }
      setImportFolderTemplate(
        (p.import_folder_template || '{name}').trim() || '{name}',
      )
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

  function applySize(w, h) {
    setWidth(w)
    setHeight(h)
    api.savePrefs({ target_width: w, target_height: h }).catch(() => {})
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

  async function runImport() {
    setError('')
    setInfo('')
    setImportProgress(null)
    setImportLog([])
    if (!importDest) {
      setError('Choose a download destination folder')
      return
    }
    const body = {
      dest: importDest,
      force: false,
      name_pattern: importNamePattern,
      folder_template: importFolderTemplate.trim() || '{name}',
    }
    if (importUrls.trim()) {
      body.name = importName.trim() || 'imported'
      body.urls = importUrls.split(/\n/).map((l) => l.trim()).filter((l) => /^https?:\/\//i.test(l))
      if (!body.urls.length) {
        setError('Paste at least one http(s) URL')
        return
      }
    } else if (importFile) {
      body.url_file = importFile
    } else if (importFolder) {
      body.url_folder = importFolder
    } else {
      setError('Paste URLs, pick a .txt file, or pick a folder of .txt files')
      return
    }
    setBusy(true)
    setImportProgress({ phase: 'start', message: 'Starting download…', done: 0, total: 0 })
    try {
      await api.savePrefs({
        import_name_pattern: importNamePattern,
        import_folder_template: importFolderTemplate.trim() || '{name}',
      }).catch(() => {})
      const res = await api.importDownload(body)
      const report = await readSse(res, (ev) => {
        if (ev.phase === 'start') {
          setImportProgress({ phase: 'start', message: `Downloading → ${ev.dest}`, done: 0, total: 0 })
          setImportLog((log) => [...log, `Start → ${ev.dest}`].slice(-12))
        } else if (ev.phase === 'download') {
          setImportProgress({
            phase: 'download',
            folder: ev.folder,
            done: ev.done,
            total: ev.total,
            label: ev.label,
            message: `${ev.folder}: ${ev.done}/${ev.total}`,
          })
          if (ev.label) {
            setImportLog((log) => {
              const line = ev.label.startsWith('failed:')
                ? `Failed ${ev.folder}: ${ev.label.slice(7)}`
                : `${ev.folder}/${ev.label} (${ev.done}/${ev.total})`
              if (log[log.length - 1] === line) return log
              return [...log, line].slice(-12)
            })
          }
        }
      })
      if (!report || report.phase === 'error' || report.error) {
        throw new Error(report?.error || 'Import failed')
      }
      setImportProgress({
        phase: 'complete',
        message: `Done · ${report.total_downloaded}/${report.total_urls}`,
        done: report.total_downloaded,
        total: report.total_urls,
      })
      setInfo(
        `Downloaded ${report.total_downloaded}/${report.total_urls}`
        + (report.total_failed ? ` (${report.total_failed} failed)` : '')
        + ` → ${report.root}`,
      )
      setBatchRoot(report.root)
      setMode('batch')
      await api.savePrefs({ mode: 'batch', last_batch_root_dir: report.root })
      await loadBatch(report.root)
    } catch (e) {
      setError(e.message)
      setImportProgress(null)
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
      } else if (mode === 'import') {
        setImportDest(dir)
      } else {
        onPickInput(dir)
      }
    }
  }

  return (
    <div className="screen" ref={dropRef} onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <div className="opener-header">
        <div>
          <h1>Focal Point Aligner</h1>
          <p className="muted">Pick a local folder, import URL lists, then align. Browse opens a folder picker.</p>
        </div>
        <div className="opener-header-actions">
          <button
            type="button"
            className="secondary"
            title="Help"
            onClick={() => onOpenHelp?.('README.md')}
          >
            Help
          </button>
          <button
            type="button"
            className="secondary"
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            onClick={() => onToggleTheme?.()}
          >
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
        </div>
      </div>

      <div className="row">
        <button className={mode === 'single' ? '' : 'secondary'} onClick={() => setMode('single')}>Single</button>
        <button className={mode === 'batch' ? '' : 'secondary'} onClick={() => setMode('batch')}>Batch</button>
        <button className={mode === 'import' ? '' : 'secondary'} onClick={() => setMode('import')}>Import</button>
      </div>

      <div className="card">
        <div className="row">
          <label>Width <input type="number" value={width} onChange={(e) => setWidth(e.target.value)} /></label>
          <label>Height <input type="number" value={height} onChange={(e) => setHeight(e.target.value)} /></label>
        </div>
        <SizePresets width={width} height={height} onChange={applySize} />
      </div>

      {mode === 'single' && (
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
      )}

      {mode === 'batch' && (
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

      {mode === 'import' && (
        <div className="card">
          <p className="muted">Paste URLs, pick a URL list `.txt`, or a folder of lists. List filenames are parsed with the pattern below into download folders, then Batch opens.</p>
          <div className="row" style={{ marginTop: 8 }}>
            <input className="grow" placeholder="Download destination" value={importDest} onChange={(e) => setImportDest(e.target.value)} />
            <button className="secondary" type="button" onClick={() => browse(setImportDest, 'Select download destination')}>Browse</button>
          </div>
          <div className="row import-pattern-row" style={{ marginTop: 12 }} title="Prefix/suffix around {name} in .txt list filenames">
            <span className="muted import-pattern-heading">List naming</span>
            <span className="import-pattern-fields">
              <input
                value={importPrefix}
                onChange={(e) => setImportPrefix(e.target.value)}
                placeholder="image_urls--"
                aria-label="Filename prefix before folder name"
              />
              <span className="import-pattern-var" title="Captured as the download folder name">{'{name}'}</span>
              <input
                value={importSuffix}
                onChange={(e) => setImportSuffix(e.target.value)}
                placeholder=""
                aria-label="Filename suffix after folder name"
                style={{ minWidth: 72 }}
              />
              <span className="muted">.txt</span>
            </span>
            <span className="muted import-pattern-example">{importNameExample}</span>
          </div>
          <div className="row import-pattern-row" style={{ marginTop: 10 }}>
            <span className="muted import-pattern-heading">Folder name</span>
            <input
              className="import-folder-template"
              value={importFolderTemplate}
              onChange={(e) => setImportFolderTemplate(e.target.value)}
              placeholder="{name}"
              aria-label="Download folder name template"
            />
            <span className="import-token-chips" role="group" aria-label="Insert folder tokens">
              {FOLDER_TOKENS.map(({ token, tip }) => (
                <button
                  key={token}
                  type="button"
                  className="secondary import-token-chip"
                  title={tip}
                  onClick={() => insertFolderToken(token)}
                >
                  {token}
                </button>
              ))}
            </span>
          </div>
          <p className="muted import-token-help">
            Tokens: <code>{'{name}'}</code> from the list file · <code>{'{n}'}</code>/<code>{'{nn}'}</code> list index · <code>{'{stem}'}</code> full filename stem.
          </p>
          <div className="row" style={{ marginTop: 12 }}>
            <input value={importName} onChange={(e) => setImportName(e.target.value)} placeholder="Folder name for pasted URLs" />
            <span className="muted">{urlCount} URL(s)</span>
          </div>
          <textarea
            className="import-urls"
            rows={6}
            placeholder={"https://example.com/a.jpg\nhttps://example.com/b.jpg"}
            value={importUrls}
            onChange={(e) => setImportUrls(e.target.value)}
          />
          <div className="row" style={{ marginTop: 12 }}>
            <input className="grow" placeholder="Or path to .txt URL list" value={importFile} onChange={(e) => setImportFile(e.target.value)} />
            <button
              className="secondary"
              type="button"
              onClick={async () => {
                try {
                  const path = await pickFile('Select URL list', ['txt', 'text'])
                  if (path) setImportFile(path)
                } catch (e) {
                  setError(e.message)
                }
              }}
            >
              File…
            </button>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <input className="grow" placeholder="Or folder of .txt lists" value={importFolder} onChange={(e) => setImportFolder(e.target.value)} />
            <button className="secondary" type="button" onClick={() => browse(setImportFolder, 'Select folder of URL lists')}>Folder…</button>
          </div>
          <div className="row" style={{ marginTop: 16 }}>
            <button disabled={busy || !importDest} onClick={runImport}>
              {busy ? 'Downloading…' : 'Download → Batch'}
            </button>
          </div>
          {(busy || importProgress) && (
            <div className="import-progress">
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <span>{importProgress?.message || 'Working…'}</span>
                {importProgress?.total > 0 && (
                  <span className="muted">{importProgress.done}/{importProgress.total}</span>
                )}
              </div>
              <div className="progress" style={{ marginTop: 8 }}>
                <div
                  style={{
                    width: `${importProgress?.total
                      ? (100 * (importProgress.done || 0)) / importProgress.total
                      : busy ? 12 : 100}%`,
                  }}
                />
              </div>
              {importLog.length > 0 && (
                <ul className="import-log">
                  {importLog.map((line, i) => (
                    <li key={`${i}-${line}`}>{line}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {error && <p className="error">{error}</p>}
      {info && <p className="ok">{info}</p>}
    </div>
  )
}
