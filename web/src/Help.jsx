import { useEffect, useMemo, useState } from 'react'
import { marked } from 'marked'
import { invoke } from '@tauri-apps/api/core'
import { isTauriApp } from './api.js'

const HELP_PAGES = [
  { id: 'README.md', label: 'Overview', file: 'README.md' },
  { id: 'getting-started.md', label: 'Getting started', file: 'getting-started.md' },
  { id: 'workflow.md', label: 'Workflow', file: 'workflow.md' },
  { id: 'keyboard.md', label: 'Keyboard', file: 'keyboard.md' },
  { id: 'video-keyframes.md', label: 'Video & keyframes', file: 'video-keyframes.md' },
  { id: 'import-batch.md', label: 'Import & batch', file: 'import-batch.md' },
  { id: 'troubleshooting.md', label: 'Troubleshooting', file: 'troubleshooting.md' },
]

const ABOUT_MD = `# About Focal Point Aligner

**Focal Point Aligner** aligns a folder of photos and videos around a focal point, then exports them to a shared frame size.

Version **0.3.0**

Desktop builds use a Tauri shell around the React + FastAPI UI. The app still needs this project checkout and \`./venv\` (or \`FPA_ROOT\` / \`FPA_PYTHON\`).

Open **User Guide** from the Help menu for the full documentation.
`

function normalizePage(page) {
  if (!page || page === 'about' || page === 'About') return 'about'
  if (page === 'index' || page === 'readme' || page === 'README') return 'README.md'
  return page.endsWith('.md') ? page : `${page}.md`
}

async function loadDocMarkdown(page) {
  const key = normalizePage(page)
  if (key === 'about') return ABOUT_MD

  if (isTauriApp()) {
    try {
      return await invoke('read_user_doc', { name: key })
    } catch {
      /* fall through to fetch */
    }
  }

  const url = `/docs/user/${key === 'README.md' ? 'README.md' : key}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Could not load ${key}`)
  return res.text()
}

/** Rewrite relative .md links in rendered HTML to stay inside the viewer. */
function rewriteDocLinks(html) {
  return html.replace(/href="([^"]+\.md)"/g, (_m, href) => {
    const file = href.split('/').pop()
    return `href="#" data-doc="${file}"`
  })
}

export default function Help({ open, page = 'README.md', onClose, onNavigate }) {
  const [markdown, setMarkdown] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const active = normalizePage(page)

  useEffect(() => {
    if (!open) return undefined
    function onKey(ev) {
      if (ev.key === 'Escape') {
        ev.preventDefault()
        ev.stopPropagation()
        onClose?.()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError('')
    loadDocMarkdown(active)
      .then((text) => {
        if (!cancelled) setMarkdown(text)
      })
      .catch((e) => {
        if (!cancelled) {
          setMarkdown('')
          setError(e.message || String(e))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [open, active])

  const html = useMemo(() => {
    if (!markdown) return ''
    return rewriteDocLinks(marked.parse(markdown, { async: false }))
  }, [markdown])

  if (!open) return null

  function onBodyClick(ev) {
    const a = ev.target.closest('a[data-doc]')
    if (!a) return
    ev.preventDefault()
    const next = a.getAttribute('data-doc')
    if (next) onNavigate?.(next)
  }

  return (
    <div className="help-modal" role="dialog" aria-modal="true" aria-label="Help">
      <div className="help-card">
        <div className="help-header">
          <h2>Help</h2>
          <button type="button" className="secondary" onClick={onClose}>Close</button>
        </div>
        <div className="help-body">
          <nav className="help-toc" aria-label="Topics">
            {HELP_PAGES.map((p) => (
              <button
                key={p.id}
                type="button"
                className={active === p.id ? 'help-toc-active' : 'secondary'}
                onClick={() => onNavigate?.(p.file)}
              >
                {p.label}
              </button>
            ))}
            <button
              type="button"
              className={active === 'about' ? 'help-toc-active' : 'secondary'}
              onClick={() => onNavigate?.('about')}
            >
              About
            </button>
          </nav>
          <div className="help-content" onClick={onBodyClick}>
            {loading && <p className="muted">Loading…</p>}
            {error && <p className="error">{error}</p>}
            {!loading && !error && (
              <div className="help-markdown" dangerouslySetInnerHTML={{ __html: html }} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
