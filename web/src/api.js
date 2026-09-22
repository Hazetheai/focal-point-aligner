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

/** Consume a Server-Sent Events response; calls onEvent for each `data:` payload. Returns the last event. */
export async function readSse(res, onEvent) {
  if (!res.body) {
    const text = await res.text()
    let last = null
    for (const block of text.split('\n\n')) {
      const line = block.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      last = JSON.parse(line.slice(6))
      onEvent?.(last)
    }
    return last
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  let last = null
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() || ''
    for (const chunk of parts) {
      const line = chunk.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      try {
        last = JSON.parse(line.slice(6))
      } catch {
        continue
      }
      onEvent?.(last)
    }
  }
  return last
}

export const api = {
  health: () => req('/health'),
  prefs: () => req('/prefs'),
  savePrefs: (body) => req('/prefs', { method: 'POST', body: JSON.stringify(body) }),
  openSession: (body) => req('/session', { method: 'POST', body: JSON.stringify(body) }),
  session: () => req('/session'),
  closeSession: () => req('/session', { method: 'DELETE' }),
  setTarget: (body) => req('/session/target', { method: 'POST', body: JSON.stringify(body) }),
  setFocal: (body) => req('/focal', { method: 'POST', body: JSON.stringify(body) }),
  clearFocal: (index) => req(`/focal${index != null ? `?index=${index}` : ''}`, { method: 'DELETE' }),
  confirm: () => req('/confirm', { method: 'POST' }),
  navigate: (body) => req('/navigate', { method: 'POST', body: JSON.stringify(body) }),
  discard: (index) => req(`/discard${index != null ? `?index=${index}` : ''}`, { method: 'POST' }),
  duplicate: () => req('/duplicate', { method: 'POST' }),
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
  importDownload: (body) => req('/import/download', { method: 'POST', body: JSON.stringify(body) }),
  arrangeAuto: (body) => req('/arrange/auto', { method: 'POST', body: JSON.stringify(body) }),
  arrangeSlot: (body) => req('/arrange/slot', { method: 'POST', body: JSON.stringify(body) }),
  arrangeRecall: (body) => req('/arrange/recall', { method: 'POST', body: JSON.stringify(body) }),
  arrangeLeave: (body) => req('/arrange/leave', { method: 'POST', body: JSON.stringify(body || { commit: true }) }),
  arrangeReverse: () => req('/arrange/reverse', { method: 'POST', body: '{}' }),
  arrangeClear: (body) => req('/arrange/clear', { method: 'POST', body: JSON.stringify(body || {}) }),
  videoRange: (body) => req('/video/range', { method: 'POST', body: JSON.stringify(body) }),
  videoSplit: (body) => req('/video/split', { method: 'POST', body: JSON.stringify(body) }),
  videoKeyframe: (body) => req('/video/keyframe', { method: 'POST', body: JSON.stringify(body) }),
  videoKeyframeMove: (body) => req('/video/keyframe/move', { method: 'POST', body: JSON.stringify(body) }),
  videoKeyframeEase: (body) => req('/video/keyframe/ease', { method: 'POST', body: JSON.stringify(body) }),
  videoKeyframeDelete: (body) => req('/video/keyframe/delete', { method: 'POST', body: JSON.stringify(body) }),
}

export function mediaUrl(kind, idx, extra = '') {
  return `${API_BASE}/media/${kind}/${idx}${extra}`
}

export async function pickFolder(title = 'Select folder') {
  if (isTauri()) {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const path = await open({ directory: true, multiple: false, title })
      if (path) return path
    } catch {
      /* fall through to the local API picker */
    }
  }
  const data = await req('/dialog/folder', {
    method: 'POST',
    body: JSON.stringify({ title }),
  })
  return data.path || null
}

export async function pickFile(title = 'Select file', types = ['txt']) {
  if (isTauri()) {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const path = await open({
        directory: false,
        multiple: false,
        title,
        filters: types?.length ? [{ name: 'Text', extensions: types }] : undefined,
      })
      if (path) return path
    } catch {
      /* fall through */
    }
  }
  const data = await req('/dialog/file', {
    method: 'POST',
    body: JSON.stringify({ title, types }),
  })
  return data.path || null
}

export function isTauriApp() {
  return isTauri()
}
