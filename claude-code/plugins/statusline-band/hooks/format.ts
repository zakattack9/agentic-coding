// Pure formatting helpers, ported from statuslineV4.sh. No engine calls here,
// so the tests can exercise them directly.

// The script's 256-color palette, by segment.
export const PALETTE = {
  dir: 117, // sky blue
  model: 147, // light purple
  effort: 186, // soft yellow (the script's version_color)
  sep: 249, // light gray
  style: 245, // gray (cc version)
  ram: 218, // pastel pink
  ctx: 116, // soft teal
  dur: 173, // muted salmon
  git: 150, // soft green
  cost: 222, // light gold
  session: 194, // light green
  sessid: 103, // muted periwinkle-gray
  ostyle: 139, // muted mauve-gray
} as const

export type Segment = keyof typeof PALETTE

const BASE16 = [
  '#000000', '#800000', '#008000', '#808000', '#000080', '#800080', '#008080', '#c0c0c0',
  '#808080', '#ff0000', '#00ff00', '#ffff00', '#0000ff', '#ff00ff', '#00ffff', '#ffffff',
]
const CUBE = [0, 95, 135, 175, 215, 255]
const hex2 = (n: number) => n.toString(16).padStart(2, '0')

// xterm-256 index to #rrggbb, so the desktop surface draws the same colors
// the terminal does for `\033[38;5;Nm`.
export function xterm256(n: number): string {
  if (n < 16) return BASE16[n] ?? '#ffffff'
  if (n < 232) {
    const i = n - 16
    const r = CUBE[Math.floor(i / 36)] ?? 0
    const g = CUBE[Math.floor((i % 36) / 6)] ?? 0
    const b = CUBE[i % 6] ?? 0
    return '#' + hex2(r) + hex2(g) + hex2(b)
  }
  const v = 8 + 10 * (n - 232)
  return '#' + hex2(v) + hex2(v) + hex2(v)
}

// `sed "s|^$HOME|~|"` then keep the last `levels` components (0 = full path).
export function shortenDir(dir: string, home: string | undefined, levels: number): string {
  let d = dir
  if (home && (d === home || d.startsWith(home + '/'))) d = '~' + d.slice(home.length)
  if (levels <= 0) return d
  const parts = d.split('/')
  return parts.length > levels ? parts.slice(parts.length - levels).join('/') : d
}

// The script drops " context": "Opus 4.8 (1M context)" -> "Opus 4.8 (1M)".
// The engine may hand back a model id instead of a display name, so ids like
// "claude-opus-5-5[1m]" are spelled out the same way: "Opus 5.5 (1M)".
export function shortenModel(model: string): string {
  const id = /^claude-([a-z]+)-(\d+)(?:-(\d+))?(?:-\d{8})?(\[1m\])?$/i.exec(model.trim())
  if (id) {
    const family = id[1] ?? ''
    const name = family.charAt(0).toUpperCase() + family.slice(1)
    const ver = id[3] ? `${id[2]}.${id[3]}` : `${id[2]}`
    return `${name} ${ver}${id[4] ? ' (1M)' : ''}`
  }
  return model.replace(' context', '')
}

export function formatDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  const days = Math.floor(s / 86400)
  const hours = Math.floor((s % 86400) / 3600)
  const mins = Math.floor((s % 3600) / 60)
  if (s < 60) return `${s}s`
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${mins}m`
  return `${mins}m`
}

// "5h 13% | 7d 7% " or '' when no window has a reading.
export function sessionText(rl5?: number, rl7?: number): string {
  const parts: string[] = []
  if (rl5 !== undefined) parts.push(`5h ${Math.trunc(rl5)}%`)
  if (rl7 !== undefined) parts.push(`7d ${Math.trunc(rl7)}%`)
  return parts.length ? parts.join(' | ') + ' ' : ''
}

// Sums `ps -o %mem=,rss=` output the way the script's awk does.
export function formatRam(psOutput: string): string {
  let mem = 0
  let rss = 0
  let found = 0
  for (const line of psOutput.split('\n')) {
    const cols = line.trim().split(/\s+/)
    if (cols.length < 2 || cols[0] === '') continue
    mem += Number(cols[0]) || 0
    rss += Number(cols[1]) || 0
    found++
  }
  if (found === 0) return 'RAM: 0.0MB (0 | 0.0%)'
  const mb = rss / 1024
  return mb >= 1000
    ? `RAM: ${(mb / 1024).toFixed(2)}GB (${found} | ${mem.toFixed(1)}%)`
    : `RAM: ${mb.toFixed(1)}MB (${found} | ${mem.toFixed(1)}%)`
}

// Unique pids from any number of `pgrep` outputs.
export function mergePids(...outputs: string[]): string[] {
  const seen = new Set<string>()
  for (const out of outputs) {
    for (const p of out.split('\n')) {
      const pid = p.trim()
      if (/^\d+$/.test(pid)) seen.add(pid)
    }
  }
  return [...seen]
}

export type Snapshot = {
  dir: string
  git: string
  model: string
  effort: string
  version: string
  sessionId: string
  outputStyle: string
  ctxPct: number
  costUsd: number
  durationMs: number
  rl5?: number
  rl7?: number
  ram: string
}

export type Piece = { text: string; seg?: Segment }

// The three rows of the script, as colored pieces.
export function rows(s: Snapshot): Piece[][] {
  const sep: Piece = { text: ' ✦ ', seg: 'sep' }

  const row1: Piece[] = [
    { text: s.dir, seg: 'dir' },
    sep,
    { text: s.git, seg: 'git' },
    sep,
    { text: s.model, seg: 'model' },
  ]
  if (s.effort) row1.push(sep, { text: s.effort, seg: 'effort' })

  const sess = sessionText(s.rl5, s.rl7)
  const row2: Piece[] = [
    { text: ' ' },
    { text: sess || 'No ongoing session ', seg: 'session' },
    { text: '✦ ', seg: 'sep' },
    { text: s.ram, seg: 'ram' },
    sep,
    { text: `${Math.trunc(s.ctxPct)}% ctx`, seg: 'ctx' },
    sep,
    { text: `$${s.costUsd.toFixed(2)}`, seg: 'cost' },
    sep,
    { text: formatDuration(s.durationMs), seg: 'dur' },
  ]

  const row3: Piece[] = [{ text: ' ' }]
  const tail: Piece[] = []
  if (s.version) tail.push({ text: `v${s.version}`, seg: 'style' })
  if (s.sessionId) tail.push({ text: s.sessionId, seg: 'sessid' })
  if (s.outputStyle) tail.push({ text: s.outputStyle, seg: 'ostyle' })
  tail.forEach((p, i) => {
    if (i > 0) row3.push(sep)
    row3.push(p)
  })

  return [row1, row2, row3]
}
