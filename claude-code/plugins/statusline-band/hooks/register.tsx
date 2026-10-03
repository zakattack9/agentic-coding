import type { EngineInterface, Register } from 'claude-code'

import {
  formatRam,
  mergePids,
  PALETTE,
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
// Live effort from the main loop's last request; the /config row is the fallback.
let liveEffort = ''
let refreshing = false
let pending = false

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

// Same process match as the script: name "claude", or a command line whose
// program path ends in /claude.
async function ramUsage($: EngineInterface) {
  const byName = await run($, ['pgrep', '-x', 'claude'])
  const byPath = await run($, ['pgrep', '-fx', '.*/claude([[:space:]].*)?$'])
  const pids = mergePids(byName?.stdout ?? '', byPath?.stdout ?? '')
  if (pids.length === 0) return formatRam('')
  const ps = await run($, ['ps', '-o', '%mem=,rss=', '-p', pids.join(',')])
  return formatRam(ps?.stdout ?? '')
}

// Effort and output style as the /config rows hold them, matched loosely so
// a renamed key still lands.
async function configValues($: EngineInterface) {
  let effort = ''
  let outputStyle = ''
  try {
    for (const row of await $.config.list()) {
      const key = row.key.toLowerCase()
      if (typeof row.value !== 'string') continue
      if (!effort && key.includes('effort')) effort = row.value
      if (!outputStyle && key.replace(/[^a-z]/g, '').includes('outputstyle')) outputStyle = row.value
    }
  } catch {
    // No config rows here: leave both empty.
  }
  return { effort, outputStyle }
}

async function collect($: EngineInterface): Promise<Snapshot> {
  const [cwd, model, id, version, usage, home, cfg, now] = await Promise.all([
    $.session.cwd(),
    $.session.model(),
    $.session.id(),
    $.session.version(),
    $.session.usage(),
    $.env.get('HOME'),
    configValues($),
    $.clock.now(),
  ])
  const [git, ram] = await Promise.all([gitBranch($, cwd), ramUsage($)])

  const rate = (kind: string) => usage.rateLimits.find(r => r.kind === kind)?.percentUsed
  const effort = liveEffort || cfg.effort
  return {
    dir: shortenDir(cwd, home, dirLevels),
    git,
    model: shortenModel(model),
    effort: effort === 'null' ? '' : effort,
    version: version.version,
    sessionId: id,
    outputStyle: cfg.outputStyle || 'default',
    ctxPct: usage.context.percent ?? 0,
    costUsd: usage.cost?.usd ?? 0,
    durationMs: now - usage.startedAt,
    rl5: rate('five_hour'),
    rl7: rate('seven_day'),
    ram,
  }
}

// One refresh at a time; a trigger that lands mid-refresh runs one more after.
async function refresh($: EngineInterface) {
  if (refreshing) {
    pending = true
    return
  }
  refreshing = true
  try {
    do {
      pending = false
      snap = await collect($)
      $.ui.invalidate('ui.render')
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
    useColor = (await $.env.get('NO_COLOR')) === undefined
    await refresh($)
    $.clock.every(refreshMs, () => {
      void refresh($)
    })
    return next(e)
  })

  // The status line's own triggers: a finished turn, a usage change, /clear.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    void refresh($)
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
    if (e.agentId === undefined && e.effort !== undefined && String(e.effort) !== liveEffort) {
      liveEffort = String(e.effort)
      void refresh($)
    }
    return yield* next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey || snap === null) return next(e)
    if (e.surface === 'terminal' && !showInTerminal) return next(e)

    const { Box, Text } = $.ui.resolve(e)
    const color = (seg?: keyof typeof PALETTE) => (useColor && seg ? xterm256(PALETTE[seg]) : undefined)

    return (
      <Box flexDirection="column" width={e.props.bodyColumns}>
        {rows(snap).map(row => (
          <Text wrap="truncate-end">
            {row.map(p => (
              <Text color={color(p.seg)}>{p.text}</Text>
            ))}
          </Text>
        ))}
      </Box>
    )
  })
}
