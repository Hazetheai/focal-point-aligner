const THEME_KEY = 'fpa-theme'

/** @returns {'light'|'dark'|'system'} */
export function getThemePreference() {
  try {
    const v = localStorage.getItem(THEME_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch { /* ignore */ }
  return 'system'
}

/** @returns {'light'|'dark'} */
export function resolveTheme(pref = getThemePreference()) {
  if (pref === 'light' || pref === 'dark') return pref
  if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark'
  }
  return 'light'
}

export function applyTheme(resolved) {
  const theme = resolved === 'light' ? 'light' : 'dark'
  document.documentElement.setAttribute('data-theme', theme)
  document.documentElement.style.colorScheme = theme
}

export function setThemePreference(pref) {
  try {
    localStorage.setItem(THEME_KEY, pref)
  } catch { /* ignore */ }
  applyTheme(resolveTheme(pref))
}

/** Toggle between light and dark (stores an explicit preference). */
export function toggleTheme() {
  const next = resolveTheme() === 'dark' ? 'light' : 'dark'
  setThemePreference(next)
  return next
}

/** Apply stored preference and watch system changes while on "system". */
export function initTheme() {
  applyTheme(resolveTheme())
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  const onChange = () => {
    if (getThemePreference() === 'system') applyTheme(resolveTheme('system'))
  }
  if (mq.addEventListener) mq.addEventListener('change', onChange)
  else if (mq.addListener) mq.addListener(onChange)
  return () => {
    if (mq.removeEventListener) mq.removeEventListener('change', onChange)
    else if (mq.removeListener) mq.removeListener(onChange)
  }
}
