import { useEffect, useState } from 'react'
import Opener from './Opener.jsx'
import Aligner from './Aligner.jsx'
import { api } from './api.js'
import { initTheme, resolveTheme, toggleTheme as flipTheme } from './theme.js'

export default function App() {
  const [screen, setScreen] = useState('opener')
  const [session, setSession] = useState(null)
  const [batchMode, setBatchMode] = useState(false)
  const [theme, setTheme] = useState(() => resolveTheme())

  useEffect(() => initTheme(), [])

  function toggleTheme() {
    setTheme(flipTheme())
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
        />
      )}
    </div>
  )
}
