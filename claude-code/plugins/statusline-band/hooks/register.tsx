import type { EngineInterface, Register } from 'claude-code'

import {
  formatEffort,
  formatRam,
  joinSide,
  type Limit,
  livePercent,
  mergePids,
  PALETTE,
  parseEtime,
  type Piece,
  rows,
  shortenDir,
  shortenModel,
  type Snapshot,
  xterm256,
} from './format'

// Options, set by register() from the manifest's userConfig.
let showInTerminal = false
let dirLevels = 3
let refreshMs = 5000

// What the band draws, rebuilt by refresh() and read by the render hook.
let snap: Snapshot | null = null
let useColor = true
// Effort from the main loop's last request: undefined until the first one
// (the /config row stands in), '' for a model that takes no effort.
let liveEffort: string | undefined
// The /config effort row and the model as last read, so a change to either
// between turns drops the last request's effort.
let lastCfgEffort: string | undefined
let lastModel: string | undefined
let refreshing = false
let pending = false

const LIMIT_LABELS: Record<string, string> = { five_hour: '5h', seven_day: '7d', spend_limit: 'spend' }

async function run($: EngineInterface, argv: string[], cwd?: string) {
  try {
    return await $.process.run(argv, { cwd, timeoutMs: 5000, env: { LC_ALL: 'C' } })
  } catch {
    return null
  }
}

async function gitBranch($: EngineInterface, cwd: string) {
  const inRepo = await run($, ['git', 'rev-parse', '--git-dir'], cwd)
  if (!inRepo || inRepo.exitCode !== 0) return 'no git'
  const branch = await run($, ['git', 'branch', '--show-current'], cwd)
  const name = branch?.exitCode === 0 ? branch.stdout.trim() : ''
  if (name) return name
  const head = await run($, ['git', 'rev-parse', '--short', 'HEAD'], cwd)
  return head?.exitCode === 0 ? head.stdout.trim() : ''
}

// The engine process this session runs in: the parent of a shell it spawns,
// kept only when that program is named "claude" (the script's ppid match).
// Its elapsed time is how long this run has been up.
async function engineProcess($: EngineInterface) {
  const sh = await run($, ['sh', '-c', 'echo $PPID'])
  const pid = sh?.exitCode === 0 ? sh.stdout.trim() : ''
  if (!/^\d+$/.test(pid)) return null
  const ps = await run($, ['ps', '-o', 'etime=,comm=', '-p', pid])
  const m = ps?.exitCode === 0 ? /^\s*(\S+)\s+(.+?)\s*$/.exec(ps.stdout) : null
  if (!m || !/(^|\/)claude$/.test(m[2] ?? '')) return null
  return { pid, uptimeMs: parseEtime(m[1] ?? '') }
}

// Same process match as the script: name "claude", a command line whose
// program path ends in /claude, or this session's own engine.
async function ramUsage($: EngineInterface, enginePid: string | undefined) {
  const byName = await run($, ['pgrep', '-x', 'claude'])
  const byPath = await run($, ['pgrep', '-fx', '.*/claude([[:space:]].*)?$'])
  const pids = mergePids(byName?.stdout ?? '', byPath?.stdout ?? '', enginePid ?? '')
  if (pids.length === 0) return formatRam('')
  const ps = await run($, ['ps', '-o', '%mem=,rss=,comm=', '-p', pids.join(',')])
  return formatRam(ps?.stdout ?? '')
}

// Effort and output style from the engine's own /config rows (a plugin's
// userConfig field named like them is skipped), matched loosely by key.
async function configValues($: EngineInterface) {
  let effort = ''
  let outputStyle = ''
  try {
    for (const row of await $.config.list()) {
      if (row.provider.plugin !== 'engine' || typeof row.value !== 'string') continue
      const key = row.key.toLowerCase()
      if (!effort && key.includes('effort')) effort = row.value
      if (!outputStyle && key.replace(/[^a-z]/g, '').includes('outputstyle')) outputStyle = row.value
    }
  } catch {
    // No config rows here: leave both empty.
  }
  return { effort, outputStyle }
}

async function collect($: EngineInterface): Promise<Snapshot> {
  const [cwd, model, id, version, usage, home, cfg, now, proc] = await Promise.all([
    $.session.cwd(),
    $.session.model(),
    $.session.id(),
    $.session.version(),
    $.session.usage(),
    $.env.get('HOME'),
    configValues($),
    $.clock.now(),
    engineProcess($),
  ])
  const [git, ram] = await Promise.all([gitBranch($, cwd), ramUsage($, proc?.pid)])

  // A /config effort or /model change since the last read beats the last
  // request's effort until the next request reports its own.
  if (lastCfgEffort !== undefined && cfg.effort !== lastCfgEffort) liveEffort = undefined
  if (lastModel !== undefined && model !== lastModel) liveEffort = undefined
  lastCfgEffort = cfg.effort
  lastModel = model
  const effort = liveEffort ?? formatEffort(cfg.effort)

  const limits: Limit[] = []
  for (const kind of ['five_hour', 'seven_day', 'spend_limit']) {
    const r = usage.rateLimits.find(x => x.kind === kind)
    if (r) limits.push({ label: LIMIT_LABELS[kind] ?? kind, pct: livePercent(r.percentUsed, r.resetsAt, now) })
  }

  // usage.startedAt is a resumed session's first launch, so count from this
  // run's start instead; /clear moves startedAt past it and wins.
  const runStart = proc?.uptimeMs !== undefined ? now - proc.uptimeMs : usage.startedAt
  return {
    dir: shortenDir(cwd, home, dirLevels),
    git,
    model: shortenModel(model),
    effort,
    version: version.version,
    sessionId: id,
    outputStyle: cfg.outputStyle || 'default',
    ctxPct: usage.context.percent,
    ctxWindow: usage.context.window,
    costUsd: usage.cost?.usd,
    durationMs: now - Math.max(runStart, usage.startedAt),
    limits,
    ram,
  }
}

// One refresh at a time; a trigger that lands mid-refresh runs one more after.
// A failed collect keeps the last snapshot.
async function refresh($: EngineInterface) {
  if (refreshing) {
    pending = true
    return
  }
  refreshing = true
  try {
    do {
      pending = false
      try {
        snap = await collect($)
        $.ui.invalidate('ui.render')
      } catch {
        // Keep drawing the last snapshot.
      }
    } while (pending)
  } finally {
    refreshing = false
  }
}

export const register: Register = (on, options) => {
  showInTerminal = options.show_in_terminal === true
  if (typeof options.dir_levels === 'number') dirLevels = options.dir_levels
  if (typeof options.refresh_seconds === 'number') refreshMs = Math.max(1, options.refresh_seconds) * 1000

  on('session.start', async ($, e, next) => {
    // Like the script's `[ -n "$NO_COLOR" ]`: an empty value keeps color.
    useColor = !(await $.env.get('NO_COLOR').catch(() => undefined))
    $.clock.every(refreshMs, () => {
      void refresh($)
    })
    // Awaited so the band is up by the first prompt; a failed collect is
    // caught inside refresh, and the timer above runs regardless.
    await refresh($)
    return next(e)
  })

  // The status line's own triggers: a finished main turn, a usage change, /clear.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined) void refresh($)
    return result
  })

  on('session.measure', async ($, e, next) => {
    void refresh($)
    return next(e)
  })

  on('classic.SessionStart', async ($, e, next) => {
    void refresh($)
    return next(e)
  })

  // The main loop's effort as each request goes out (subagents skipped).
  on('turn.step', async function* ($, e, next) {
    if (e.agentId === undefined) {
      const effort = formatEffort(e.effort)
      if (effort !== liveEffort) {
        liveEffort = effort
        void refresh($)
      }
    }
    return yield* next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey || snap === null) return next(e)
    if (e.surface === 'terminal' && !showInTerminal) return next(e)

    const { Box, Text } = $.ui.resolve(e)
    const draw = (pieces: Piece[]) =>
      pieces.map(p => (
        <Text
          color={useColor && p.seg ? xterm256(PALETTE[p.seg]) : useColor && p.isLabel ? xterm256(PALETTE.sep) : undefined}
          dimColor={p.isLabel === true}
        >
          {p.text}
        </Text>
      ))

    // Each row: the left side from the start, the right side pushed to the
    // far edge. When the band is too narrow, the right side gives way first.
    return (
      <Box flexDirection="column" width={e.props.bodyColumns}>
        {rows(snap).map(row => (
          <Box flexDirection="row" justifyContent="space-between" columnGap={3}>
            <Text wrap="truncate-end">{draw(joinSide(row.left))}</Text>
            <Box flexShrink={1000}>
              <Text wrap="truncate-start">{draw(joinSide(row.right))}</Text>
            </Box>
          </Box>
        ))}
      </Box>
    )
  })
}
