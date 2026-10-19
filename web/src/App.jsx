import { useEffect, useState } from 'react'
import Opener from './Opener.jsx'
import Aligner from './Aligner.jsx'
import Help from './Help.jsx'
import { api, isTauriApp } from './api.js'
import { initTheme, resolveTheme, toggleTheme as flipTheme } from './theme.js'

export default function App() {
  const [screen, setScreen] = useState('opener')
  const [session, setSession] = useState(null)
  const [batchMode, setBatchMode] = useState(false)
  const [theme, setTheme] = useState(() => resolveTheme())
  const [helpOpen, setHelpOpen] = useState(false)
  const [helpPage, setHelpPage] = useState('README.md')

  useEffect(() => initTheme(), [])

  useEffect(() => {
    if (!isTauriApp()) return undefined
    let cancelled = false
    let unlisten = null
    import('@tauri-apps/api/event')
      .then(({ listen }) => listen('open-docs', (ev) => {
        const page = ev?.payload?.page || 'README.md'
        setHelpPage(page)
        setHelpOpen(true)
      }))
      .then((fn) => {
        if (cancelled) fn()
        else unlisten = fn
      })
      .catch(() => {})
    return () => {
      cancelled = true
      if (typeof unlisten === 'function') unlisten()
    }
  }, [])

  function toggleTheme() {
    setTheme(flipTheme())
  }

  function openHelp(page = 'README.md') {
    setHelpPage(page)
    setHelpOpen(true)
  }

  async function finish() {
    if (batchMode) {
      try {
        const nxt = await api.batchNext()
        if (!nxt.done && nxt.session) {
          setSession(nxt.session)
          setScreen('aligner')
          return
        }
      } catch {
        /* fall through to opener */
      }
    }
    try { await api.closeSession() } catch { /* ignore */ }
    setSession(null)
    setBatchMode(false)
    setScreen('opener')
  }

  return (
    <div className="app">
      {screen === 'opener' && (
        <Opener
          theme={theme}
          onToggleTheme={toggleTheme}
          onOpenHelp={openHelp}
          onStart={(s) => { setBatchMode(false); setSession(s); setScreen('aligner') }}
          onBatchSession={(s) => { setBatchMode(true); setSession(s); setScreen('aligner') }}
        />
      )}
      {screen === 'aligner' && session && (
        <Aligner
          session={session}
          setSession={setSession}
          batchMode={batchMode}
          onFinished={finish}
          theme={theme}
          onToggleTheme={toggleTheme}
          onOpenHelp={openHelp}
        />
      )}
      <Help
        open={helpOpen}
        page={helpPage}
        onClose={() => setHelpOpen(false)}
        onNavigate={(page) => setHelpPage(page)}
      />
    </div>
  )
}
