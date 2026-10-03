import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import { formatDuration, formatRam, shortenDir, shortenModel, xterm256 } from '../hooks/format'

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
function world(on: On) {
  mock.env(on, { HOME: '/Users/z' })
  const clock = mock.clock(on, { now: 1_000_000 + 3_725_000 })
  on('session.cwd', async () => ({ value: '/Users/z/dev/presspoint/api/src' }))
  on('session.model', async () => ({ value: 'claude-opus-5-5[1m]' }))
  on('session.id', async () => ({ value: 'abc-123' }))
  on('session.version', async () => ({ value: { version: '2.1.288', base: '2.1.288' } }))
  on('session.usage', async () => ({ value: {
    startedAt: 1_000_000,
    context: { tokens: 42_000, window: 200_000, percent: 21 },
    rateLimits: [
      { kind: 'five_hour', percentUsed: 13.4 },
      { kind: 'seven_day', percentUsed: 7.9 },
    ],
    cost: { usd: 1.234 },
  } }))
  on('session.start', async ($, e) => ({ cwd: e.cwd }))
  on('config.list', async () => ({ value: [] }))
  const out = (exitCode: number, stdout: string) => ({
    value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
  })
  on('process.run', async ($, e) => {
    const argv = e.argv.join(' ')
    if (argv === 'git rev-parse --git-dir') return out(0, '.git\n')
    if (argv === 'git branch --show-current') return out(0, 'main\n')
    if (argv.startsWith('pgrep -x')) return out(0, '101\n102\n')
    if (argv.startsWith('pgrep -fx')) return out(0, '102\n')
    if (argv.startsWith('ps ')) return out(0, ' 1.5 307200\n 0.5 204800\n')
    return out(1, '')
  })
  return clock
}

test('draws the three rows on desktop', async ($, on) => {
  world(on)
  await $.session.start({ cwd: '/Users/z/dev/presspoint/api/src', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: 'api/src' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'main' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Opus 5.5 (1M)' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '5h 13% | 7d 7% ' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'RAM: 500.0MB (2 | 2.0%)' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '21% ctx' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '$1.23' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '1h 2m' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'v2.1.288' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'abc-123' })).toBeDefined()
  await ui.unmount()
})

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
  expect(await ui.find({ type: 'Text', text: 'ctx' })).toBeUndefined()
  await ui.unmount()
})

test('draws in the terminal when asked to', { options: { show_in_terminal: true } }, async ($, on) => {
  world(on)
  await $.session.start({ cwd: '/Users/z', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: '21% ctx' })).toBeDefined()
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
  expect(formatRam('')).toBe('RAM: 0.0MB (0 | 0.0%)')
  expect(formatRam(' 3.0 1572864\n')).toBe('RAM: 1.50GB (1 | 3.0%)')
})
