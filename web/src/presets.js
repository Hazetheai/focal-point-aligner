/** Target size presets: ratio × typical web/social/film resolutions (landscape). */
export const SIZE_RATIOS = [
  {
    id: '16:9',
    label: '16:9',
    sizes: [
      [1280, 720],
      [1920, 1080],
      [2560, 1440],
      [3840, 2160],
    ],
  },
  {
    id: '2:1',
    label: '2:1',
    sizes: [
      [1280, 640],
      [1920, 960],
      [2560, 1280],
      [3840, 1920],
    ],
  },
  {
    id: '1:1',
    label: '1:1',
    sizes: [
      [1080, 1080],
      [1440, 1440],
      [2048, 2048],
    ],
  },
  {
    id: '4:5',
    label: '4:5',
    sizes: [
      [1080, 1350],
      [1440, 1800],
      [2160, 2700],
    ],
  },
  {
    id: '4:3',
    label: '4:3',
    sizes: [
      [1280, 960],
      [1600, 1200],
      [2048, 1536],
      [2560, 1920],
    ],
  },
]

export function matchRatio(width, height) {
  const w = Number(width)
  const h = Number(height)
  if (!w || !h) return null
  const r = w / h
  let best = null
  let bestDiff = Infinity
  for (const preset of SIZE_RATIOS) {
    const [a, b] = preset.id.split(':').map(Number)
    const pr = a / b
    const diff = Math.abs(r - pr)
    if (diff < bestDiff) {
      bestDiff = diff
      best = preset.id
    }
  }
  return bestDiff < 0.02 ? best : null
}

export function sizeLabel([w, h]) {
  return `${w}×${h}`
}
