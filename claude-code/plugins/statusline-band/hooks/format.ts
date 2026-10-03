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

// turn.step's effort: a level name, or a thinking budget in tokens.
export function formatEffort(effort: string | number | undefined): string {
  if (effort === undefined) return ''
  if (typeof effort === 'number') return formatTokens(effort)
  return effort === 'null' ? '' : effort
}

// 1_000_000 -> "1M", 200_000 -> "200k", 32_000 -> "32k".
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`
  if (n >= 1000) return `${Math.round(n / 1000)}k`
  return `${n}`
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

// `ps -o etime=` ("[[dd-]hh:]mm:ss") to milliseconds; undefined when unparsable.
export function parseEtime(etime: string): number | undefined {
  const m = /^(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)$/.exec(etime.trim())
  if (!m) return undefined
  const [d, h, min, s] = [m[1], m[2], m[3], m[4]].map(x => Number(x ?? 0))
  return (((d ?? 0) * 24 + (h ?? 0)) * 60 + (min ?? 0)) * 60_000 + (s ?? 0) * 1000
}

// A window's percent, or 0 once its reset time has passed: the reading is from
// the last API response, which may predate the reset by hours.
export function livePercent(percentUsed: number, resetsAt: string | undefined, now: number): number {
  const t = resetsAt ? Date.parse(resetsAt) : NaN
  return Number.isFinite(t) && t <= now ? 0 : percentUsed
}

// "f00a9b5b-d316-4fca-9031-1b5fa9afddad" -> "f00a9b5b…afddad".
export function shortenId(id: string): string {
  return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-6)}` : id
}

export type Ram = { amount: string; procs: number; pct: string }

// Sums `ps -o %mem=,rss=,comm=` output the way the script's awk does, keeping
// only programs named exactly "claude": a wrapper whose arguments end in a
// claude path (the Desktop app's `disclaimer`) matches `pgrep -f` but isn't one.
export function formatRam(psOutput: string): Ram {
  let mem = 0
  let rss = 0
  let found = 0
  for (const line of psOutput.split('\n')) {
    const m = /^\s*([\d.]+)\s+(\d+)\s+(.+?)\s*$/.exec(line)
    if (!m || !/(^|\/)claude$/.test(m[3] ?? '')) continue
    mem += Number(m[1]) || 0
    rss += Number(m[2]) || 0
    found++
  }
  const mb = rss / 1024
  const amount = mb >= 1000 ? `${(mb / 1024).toFixed(2)}GB` : `${mb.toFixed(1)}MB`
  return { amount, procs: found, pct: `${mem.toFixed(1)}%` }
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

export type Limit = { label: string; pct: number }

export type Snapshot = {
  dir: string
  git: string
  model: string
  effort: string
  version: string
  sessionId: string
  outputStyle: string
  // Absent until the live window's first response (a fresh or just-compacted session).
  ctxPct?: number
  ctxWindow: number
  // Absent where the host keeps no cost ledger.
  costUsd?: number
  durationMs: number
  limits: Limit[]
  ram: Ram
}

// One run of text; `seg` colors it, `isDim` draws it quiet, and `copy` makes
// it a button that copies that text.
export type Piece = { text: string; seg?: Segment; isDim?: boolean; copy?: string }
// Segments are joined by the separator; each is one or more pieces.
export type Side = Piece[][]
export type Row = { left: Side; right: Side }

// Two rows, each split into a left side (what changes the reading of the
// session) and a right side pushed to the band's far edge:
//   dir ◦ branch ◦ model ◦ effort                 style ◦ version ◦ session id
//   5h 13% ◦ 7d 26% ◦ ctx 8% of 1M ◦ $0.77 ◦ 2m      RAM 2.03GB (7 · 3.1%)
export function rows(s: Snapshot): Row[] {
  const row1: Row = {
    left: [[{ text: s.dir, seg: 'dir' }], [{ text: s.git, seg: 'git' }], [{ text: s.model, seg: 'model' }]],
    right: [],
  }
  if (s.effort) row1.left.push([{ text: s.effort, seg: 'effort' }])
  if (s.outputStyle) row1.right.push([{ text: s.outputStyle, seg: 'ostyle' }])
  if (s.version) row1.right.push([{ text: `v${s.version}`, seg: 'style' }])
  if (s.sessionId) row1.right.push([{ text: shortenId(s.sessionId), seg: 'sessid', copy: s.sessionId }])

  const row2: Row = { left: [], right: [] }
  for (const l of s.limits) {
    row2.left.push([{ text: `${l.label} ${Math.trunc(l.pct)}%`, seg: 'session' }])
  }
  const ctx = s.ctxPct === undefined ? '—' : `${Math.trunc(s.ctxPct)}%`
  row2.left.push([{ text: `ctx ${ctx} of ${formatTokens(s.ctxWindow)}`, seg: 'ctx' }])
  if (s.costUsd !== undefined) row2.left.push([{ text: `$${s.costUsd.toFixed(2)}`, seg: 'cost' }])
  row2.left.push([{ text: formatDuration(s.durationMs), seg: 'dur' }])
  row2.right.push([{ text: `RAM ${s.ram.amount} (${s.ram.procs} · ${s.ram.pct})`, seg: 'ram' }])

  return [row1, row2]
}

// A side as one flat run of pieces, separators included.
export function joinSide(side: Side): Piece[] {
  const out: Piece[] = []
  side.forEach((seg, i) => {
    if (i > 0) out.push({ text: ' ◦ ', seg: 'sep', isDim: true })
    out.push(...seg)
  })
  return out
}
