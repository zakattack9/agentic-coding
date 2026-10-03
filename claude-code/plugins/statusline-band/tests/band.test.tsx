import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import {
  formatDuration,
  formatEffort,
  formatRam,
  formatTokens,
  joinSide,
  livePercent,
  parseEtime,
  shortenDir,
  shade,
  shortenId,
  shortenModel,
  xterm256,
} from '../hooks/format'

const BAND = {
  plugin: 'statusline-band',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 10,
    bodyColumns: 160,
    scroll: { offset: 0, bodyRows: 10 },
    view: {},
  },
} as const

// The world beneath the plugin: a session in a git repo on a Mac.
function world(on: On, usage: Record<string, unknown> = {}, engineComm = '/Apps/claude.app/Contents/MacOS/claude') {
  mock.env(on, { HOME: '/Users/z' })
  const clock = mock.clock(on, { now: 1_000_000 + 3_725_000 })
  on('session.cwd', async () => ({ value: '/Users/z/dev/presspoint/api/src' }))
  on('session.model', async () => ({ value: 'claude-opus-5-5[1m]' }))
  on('session.id', async () => ({ value: 'f00a9b5b-d316-4fca-9031-1b5fa9afddad' }))
  on('session.version', async () => ({ value: { version: '2.1.288', base: '2.1.288' } }))
  on('session.usage', async () => ({ value: {
    startedAt: 1_000_000,
    context: { tokens: 42_000, window: 1_000_000, percent: 21 },
    rateLimits: [
      { kind: 'five_hour', percentUsed: 13.4 },
      { kind: 'seven_day', percentUsed: 7.9 },
    ],
    cost: { usd: 1.234 },
    ...usage,
  } }))
  on('session.start', async ($, e) => ({ cwd: e.cwd }))
  on('config.list', async () => ({ value: [] }))
  on('classic.SessionStart', async () => ({}))
  const out = (exitCode: number, stdout: string) => ({
    value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
  })
  on('process.run', async ($, e) => {
    const argv = e.argv.join(' ')
    if (argv === 'git rev-parse --git-dir') return out(0, '.git\n')
    if (argv === 'git branch --show-current') return out(0, 'main\n')
    if (argv === 'sh -c echo $PPID') return out(0, '103\n')
    if (argv === 'ps -o etime=,comm= -p 103') return out(0, `   20:00 ${engineComm}\n`)
    if (argv.startsWith('pgrep -x')) return out(0, '101\n102\n')
    if (argv.startsWith('pgrep -fx')) return out(0, '102\n104\n')
    if (argv.startsWith('ps -o %mem=,rss=,comm= -p ')) {
      return out(0, ' 1.0 204800 claude\n 0.5 102400 /Users/z/.local/bin/claude\n 0.0 688 /Apps/Helpers/disclaimer\n 0.5 204800 /Apps/claude.app/Contents/MacOS/claude\n')
    }
    return out(1, '')
  })
  return clock
}

test('draws two rows on desktop', async ($, on) => {
  world(on)
  await $.session.start({ cwd: '/Users/z/dev/presspoint/api/src', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  for (const text of [
    'presspoint/api/src', 'main', 'Opus 5.5 (1M)', 'default', 'v2.1.288',
    '5h 13% · 7d 7%', 'ctx 21%', '$1.23',
    // Uptime of this run (the engine's etime), not usage.startedAt (1h 2m ago).
    '20m',
    // Three claude processes; the disclaimer wrapper is dropped.
    '500.0MB', ' (3 · 2.0%)',
  ]) {
    expect(await ui.find({ type: 'Text', text })).toBeDefined()
  }
  expect(await ui.find({ type: 'Button', key: 'copy-session-id', text: 'f00a9b5b…afddad' })).toBeDefined()
  await ui.unmount()
})

test('leaves out what the engine has no figure for', async ($, on) => {
  world(on, { context: { window: 200_000 }, rateLimits: [], cost: undefined })
  await $.session.start({ cwd: '/Users/z', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: '—' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '5h ' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: '$1.23' })).toBeUndefined()
  await ui.unmount()
})

test('reads a rate-limit window past its reset as 0%', async ($, on) => {
  world(on, { rateLimits: [{ kind: 'five_hour', percentUsed: 13.4, resetsAt: '1970-01-01T00:00:01Z' }] })
  await $.session.start({ cwd: '/Users/z', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: '5h 0%' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '13%' })).toBeUndefined()
  await ui.unmount()
})

test('counts duration from /clear when it is later than the engine start', async ($, on) => {
  // The mocked clock reads 4_725_000; /clear 5 minutes ago, engine up 20m.
  world(on, { startedAt: 4_425_000 })
  await $.session.start({ cwd: '/Users/z', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: '5m' })).toBeDefined()
  await ui.unmount()
})

test('falls back to the session start when the parent is not claude', async ($, on) => {
  world(on, {}, '/usr/bin/node')
  await $.session.start({ cwd: '/Users/z', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: '1h 2m' })).toBeDefined()
  await ui.unmount()
})

for (const [surface, copied, toast] of [
  ['terminal', true, 'Session ID copied'],
  ['desktop', false, 'Session ID: f00a9b5b-d316-4fca-9031-1b5fa9afddad'],
] as const) {
  test(`copies the session id on ${surface}`, { options: { show_in_terminal: true } }, async ($, on) => {
    world(on)
    const copies: string[] = []
    on('ui.copy', async ($, e) => {
      copies.push(e.text)
      return { value: copied ? { isCopied: true } : { isCopied: false, reason: 'no-clipboard' } }
    })
    const toasts: string[] = []
    on('ui.toast', async ($, e) => {
      toasts.push(e.text)
      return { value: undefined }
    })
    await $.session.start({ cwd: '/Users/z', surface, isInteractive: true })
    const ui = await $.ui.mount({ ...BAND, surface })
    await ui.press({ key: 'copy-session-id' })
    expect(copies).toEqual(['f00a9b5b-d316-4fca-9031-1b5fa9afddad'])
    expect(toasts).toEqual([toast])
    await ui.unmount()
  })
}

test('leaves the terminal band to the real status line by default', async ($, on) => {
  world(on)
  // The engine's own band, which the mod passes to: a marker the test can find.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine band</Text>
  })
  await $.session.start({ cwd: '/Users/z', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'engine band' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '21%' })).toBeUndefined()
  await ui.unmount()
})

test('draws in the terminal when asked to', { options: { show_in_terminal: true } }, async ($, on) => {
  world(on)
  await $.session.start({ cwd: '/Users/z', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: '21%' })).toBeDefined()
  await ui.unmount()
})

test('formatting matches the script', async () => {
  expect(xterm256(117)).toBe('#87d7ff')
  expect(xterm256(249)).toBe('#b2b2b2')
  expect(shortenDir('/Users/z/a/b/c/d', '/Users/z', 3)).toBe('b/c/d')
  expect(shortenDir('/Users/z/a', '/Users/z', 3)).toBe('~/a')
  expect(shortenDir('/Users/z/a/b/c', '/Users/z', 0)).toBe('~/a/b/c')
  expect(shortenModel('Opus 4.8 (1M context)')).toBe('Opus 4.8 (1M)')
  expect(shortenModel('claude-sonnet-5-5')).toBe('Sonnet 5.5')
  expect(formatDuration(42_000)).toBe('42s')
  expect(formatDuration(3_725_000)).toBe('1h 2m')
  expect(formatDuration(90_000_000)).toBe('1d 1h')
  expect(formatRam('')).toEqual({ amount: '0.0MB', procs: 0, pct: '0.0%' })
  expect(formatRam(' 3.0 1572864 claude\n')).toEqual({ amount: '1.50GB', procs: 1, pct: '3.0%' })
  expect(formatRam(' 0.0 688 /Apps/Helpers/disclaimer\n')).toEqual({ amount: '0.0MB', procs: 0, pct: '0.0%' })
})

test('formatting the band adds', async () => {
  expect(formatEffort(undefined)).toBe('')
  expect(formatEffort('xhigh')).toBe('xhigh')
  expect(formatEffort(32_000)).toBe('32k')
  expect(formatTokens(1_000_000)).toBe('1M')
  expect(formatTokens(200_000)).toBe('200k')
  expect(parseEtime('18:04')).toBe(1_084_000)
  expect(parseEtime('04:11:56')).toBe(15_116_000)
  expect(parseEtime('02-01:39:38')).toBe(178_778_000)
  expect(parseEtime('junk')).toBeUndefined()
  const now = Date.parse('2026-10-02T12:00:00Z')
  expect(livePercent(13.4, '2026-10-02T11:00:00Z', now)).toBe(0)
  expect(livePercent(13.4, '2026-10-02T13:00:00Z', now)).toBe(13.4)
  expect(livePercent(13.4, undefined, now)).toBe(13.4)
  expect(shortenId('f00a9b5b-d316-4fca-9031-1b5fa9afddad')).toBe('f00a9b5b…afddad')
  expect(shortenId('abc-123')).toBe('abc-123')
  expect(shade('#ffd7af')).toBe('#bfa183')
  const side = [[{ text: 'a' }], [{ text: 'id', copy: 'full-id' }]]
  const text = (padded: boolean) => joinSide(side, padded).map(p => p.text).join('')
  expect(text(false)).toBe('a\u00a0\u00a0⟡\u00a0\u00a0id')
  expect(text(true)).toBe('a\u00a0\u00a0⟡id')
})
