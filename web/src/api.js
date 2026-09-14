const isTauri = () => typeof window !== 'undefined' && Boolean(window.__TAURI_INTERNALS__)

export const API_BASE = isTauri()
  ? (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8765')
  : (import.meta.env.VITE_API_URL || '')

async function req(path, opts = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('text/event-stream')) return res
  if (ct.includes('application/json')) return res.json()
  return res
}

export const api = {
  health: () => req('/health'),
  prefs: () => req('/prefs'),
  savePrefs: (body) => req('/prefs', { method: 'POST', body: JSON.stringify(body) }),
  openSession: (body) => req('/session', { method: 'POST', body: JSON.stringify(body) }),
  session: () => req('/session'),
  closeSession: () => req('/session', { method: 'DELETE' }),
  setFocal: (body) => req('/focal', { method: 'POST', body: JSON.stringify(body) }),
  clearFocal: (index) => req(`/focal${index != null ? `?index=${index}` : ''}`, { method: 'DELETE' }),
  confirm: () => req('/confirm', { method: 'POST' }),
  navigate: (body) => req('/navigate', { method: 'POST', body: JSON.stringify(body) }),
  discard: (index) => req(`/discard${index != null ? `?index=${index}` : ''}`, { method: 'POST' }),
  order: (order) => req('/order', { method: 'POST', body: JSON.stringify({ order }) }),
  shift: (direction) => req(`/shift?direction=${direction}`, { method: 'POST' }),
  setMode: (mode) => req('/mode', { method: 'POST', body: JSON.stringify({ mode }) }),
  crop: (idx, orientation) => req(`/crop/${idx}${orientation ? `?orientation=${orientation}` : ''}`),
  export: (body) => req('/export', { method: 'POST', body: JSON.stringify(body) }),
  reset: () => req('/reset', { method: 'POST' }),
  openBatch: (root) => req('/batch', { method: 'POST', body: JSON.stringify({ root }) }),
  getBatch: () => req('/batch'),
  batchNext: () => req('/batch/next', { method: 'POST' }),
  merge: (body) => req('/batch/merge', { method: 'POST', body: JSON.stringify(body) }),
  moveAligned: (root) => req(`/batch/move-aligned${root ? `?root=${encodeURIComponent(root)}` : ''}`, { method: 'POST' }),
}

export function mediaUrl(kind, idx, extra = '') {
  return `${API_BASE}/media/${kind}/${idx}${extra}`
}

export async function pickFolder() {
  if (isTauri()) {
    const { open } = await import('@tauri-apps/plugin-dialog')
    return open({ directory: true, multiple: false })
  }
  return null
}

export function isTauriApp() {
  return isTauri()
}
