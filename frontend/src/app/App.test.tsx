import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AttemptResult, PuzzleView } from '../api/types'
import { cardName } from '../lib/cards'
import { SHORTCUTS } from '../lib/shortcuts'
import {
  attemptFixture,
  historyFixture,
  puzzleFixture,
  settingsFixture,
  statsFixture,
} from '../test/fixture'
import { App } from './App'

interface Call {
  method: string
  url: string
  body: unknown
}

/**
 * A fake server behind `fetch`, recording every request: the real client runs, so the test sees
 * exactly which endpoints the UI calls.
 */
function fakeServer(
  opts: {
    puzzles?: PuzzleView[]
    attempt?: AttemptResult
    /** the answer to `GET /api/stats?tz=…` (default: the stats fixture) */
    stats?: (tz: string) => { status: number; body: unknown }
  } = {},
) {
  const calls: Call[] = []
  const puzzles = [...(opts.puzzles ?? [puzzleFixture('flop_unopened'), puzzleFixture('river')])]
  const attempt = opts.attempt ?? attemptFixture('bet')
  const json = (status: number, data: unknown) =>
    new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : undefined
    calls.push({ method, url, body })
    if (url === '/api/settings' && method === 'GET') return json(200, settingsFixture())
    if (url === '/api/settings' && method === 'PATCH') {
      return json(200, { ...settingsFixture(), ...(body as object) })
    }
    if (url.startsWith('/api/stats?tz=')) {
      const tz = decodeURIComponent(url.slice('/api/stats?tz='.length))
      // the stats count days against the same goal the settings hold
      const stats = statsFixture()
      stats.days = { ...stats.days, goal: settingsFixture().daily_goal }
      const answer = opts.stats?.(tz) ?? { status: 200, body: stats }
      return json(answer.status, answer.body)
    }
    if (url.startsWith('/api/history')) return json(200, historyFixture())
    const stored = /^\/api\/puzzles\/(\d+)$/.exec(url)
    if (stored && method === 'GET') {
      // a stored puzzle that has been answered before: a replay
      return json(200, { ...puzzleFixture('river'), id: Number(stored[1]), attempts_so_far: 1 })
    }
    if (/^\/api\/attempts\/\d+$/.test(url) && method === 'GET') return json(200, attempt)
    if (url === '/api/puzzles/current') return json(404, { detail: 'no current puzzle' })
    if (url === '/api/puzzles' && method === 'POST') {
      const next = puzzles.shift()
      return next ? json(201, next) : json(503, { detail: 'generation failed' })
    }
    if (/^\/api\/puzzles\/\d+\/attempts$/.test(url) && method === 'POST') {
      return json(201, attempt)
    }
    return json(404, { detail: 'Not Found' })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls }
}

function setup() {
  const user = userEvent.setup()
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
  return { user }
}

/** A face-up card anywhere in the DOM (board cards sit in an aria-hidden row). */
const inDom = (card: string) =>
  document.querySelector(`[data-face="up"][data-rank="${card[0]}"][data-suit="${card[1]}"]`)

const villainSeat = () => screen.getByRole('group', { name: /^Villain,/ })

async function answerCheck(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByRole('textbox', { name: 'Equity' }), '45')
  await user.click(screen.getByRole('button', { name: /^Check/ }))
  await user.click(screen.getByRole('button', { name: /^Submit/ }))
}

beforeEach(() => {
  window.localStorage.clear()
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('loads once under StrictMode: one GET current, one POST', async () => {
    const { calls } = fakeServer()
    setup()
    await screen.findByRole('textbox', { name: 'Equity' })
    const puzzleCalls = calls.filter((c) => c.url.startsWith('/api/puzzles'))
    expect(puzzleCalls.map((c) => `${c.method} ${c.url}`)).toEqual([
      'GET /api/puzzles/current',
      'POST /api/puzzles',
    ])
    expect(calls.filter((c) => c.url === '/api/settings')).toHaveLength(1)
  })

  it('hides Villain and the run-out until the submit, and calls no answer endpoint before it', async () => {
    const { calls } = fakeServer()
    const view = puzzleFixture('flop_unopened')
    const attempt = attemptFixture('bet')
    const { user } = setup()
    await screen.findByRole('textbox', { name: 'Equity' })

    expect(within(villainSeat()).getAllByRole('img', { name: 'face-down card' })).toHaveLength(2)
    for (const card of attempt.reveal.villain_cards) expect(inDom(card)).toBeNull()
    const undealt = attempt.reveal.runout.slice(view.board.length)
    expect(undealt.length).toBeGreaterThan(0)
    for (const card of undealt) {
      expect(inDom(card)).toBeNull()
      expect(document.body.textContent).not.toContain(cardName(card))
    }
    const allowed = /^\/api\/(settings|puzzles|puzzles\/current|health)$/
    expect(calls.every((c) => allowed.test(c.url))).toBe(true)

    await answerCheck(user)
    expect(await screen.findByRole('region', { name: 'Result' })).toHaveTextContent('Best')
    for (const card of attempt.reveal.villain_cards) {
      expect(within(villainSeat()).getByRole('img', { name: cardName(card) })).toBeVisible()
    }
    for (const card of undealt) expect(inDom(card)).not.toBeNull()
    const submits = calls.filter((c) => c.url.endsWith('/attempts'))
    expect(submits).toEqual([
      { method: 'POST', url: `/api/puzzles/${view.id}/attempts`, body: expect.anything() },
    ])
  })

  it('deals no run-out after a fold, and the full board after a bet', async () => {
    const view = puzzleFixture('facing_postflop_raise')
    const fold = attemptFixture('fold')
    fakeServer({ puzzles: [view], attempt: fold })
    const { user } = setup()
    await user.type(await screen.findByRole('textbox', { name: 'Equity' }), '45')
    await user.click(screen.getByRole('button', { name: /^Fold/ }))
    await user.click(screen.getByRole('button', { name: /^Submit/ }))
    await screen.findByRole('region', { name: 'Result' })
    expect(document.querySelectorAll('[data-face="up"]').length).toBeGreaterThan(0)
    for (const card of fold.reveal.runout.slice(view.board.length)) expect(inDom(card)).toBeNull()
    for (const card of view.board) expect(inDom(card)).not.toBeNull()
  })

  it('shows all five board cards after a bet', async () => {
    fakeServer()
    const attempt = attemptFixture('bet')
    const { user } = setup()
    await answerCheck(user)
    await screen.findByRole('region', { name: 'Result' })
    for (const card of attempt.reveal.runout) expect(inDom(card)).not.toBeNull()
  })

  it('announces the verdict, shows the answer in the history, and focuses Next', async () => {
    fakeServer()
    const { user } = setup()
    await screen.findByRole('textbox', { name: 'Equity' })
    // the live region exists, empty, before the result: an inserted, pre-filled one is not read
    const status = screen.getByTestId('announcer')
    expect(status).toHaveAttribute('role', 'status')
    expect(status).toBeEmptyDOMElement()
    await answerCheck(user)
    await waitFor(() => expect(status).toHaveTextContent('Best.'))
    expect(screen.getByTestId('announcer')).toBe(status)
    expect(status).toHaveTextContent('You: Bet 33% · the top play')
    expect(screen.queryByText('Hero to act')).toBeNull()
    expect(screen.getByText('your answer')).toBeVisible()
    expect(screen.getByRole('button', { name: /Next puzzle/ })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'Options' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('table')).toBeVisible()
  })

  it('N after a result loads the next puzzle and keeps focus on the page', async () => {
    const { calls } = fakeServer()
    const { user } = setup()
    await answerCheck(user)
    await screen.findByRole('button', { name: /Next puzzle/ })
    await user.keyboard('n')
    // the river puzzle: no range read
    await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Range read' })).toBeNull())
    expect(await screen.findByRole('textbox', { name: 'Equity' })).toBeVisible()
    expect(calls.filter((c) => c.method === 'POST' && c.url === '/api/puzzles')).toHaveLength(2)
    expect(document.activeElement).not.toBe(document.body)
    expect(screen.getByText('Hero to act')).toBeVisible()
  })

  it('N while answering asks first; Escape cancels; N N skips', async () => {
    const { calls } = fakeServer()
    const { user } = setup()
    await screen.findByRole('textbox', { name: 'Equity' })
    const posts = () => calls.filter((c) => c.method === 'POST' && c.url === '/api/puzzles')

    await user.keyboard('n')
    expect(screen.getByText(/Skip this puzzle\?/)).toBeVisible()
    await user.keyboard('{Escape}')
    expect(screen.queryByText(/Skip this puzzle\?/)).toBeNull()
    expect(posts()).toHaveLength(1)

    await user.keyboard('nn')
    await waitFor(() => expect(posts()).toHaveLength(2))
    await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Range read' })).toBeNull())
  })

  it('with shortcuts off, N and ? do nothing', async () => {
    fakeServer()
    const { user } = setup()
    await screen.findByRole('textbox', { name: 'Equity' })
    await user.click(screen.getByRole('switch', { name: 'Shortcuts' }))
    expect(window.localStorage.getItem('ppt.shortcuts')).toBe('off')
    await user.keyboard('n?')
    expect(screen.queryByText(/Skip this puzzle\?/)).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('? opens the shortcuts overlay; keys do not reach the page behind it', async () => {
    const { calls } = fakeServer()
    const { user } = setup()
    await screen.findByRole('textbox', { name: 'Equity' })
    await user.keyboard('?')
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeVisible()
    await user.keyboard('nnx')
    expect(screen.queryByText(/Skip this puzzle\?/)).toBeNull()
    expect(screen.getByRole('button', { name: /^Check/ })).toHaveAttribute('aria-pressed', 'false')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it('the top bar toggles patch the settings', async () => {
    const { calls } = fakeServer()
    const { user } = setup()
    await screen.findByRole('textbox', { name: 'Equity' })
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'Show profile' })).toHaveAttribute(
        'aria-checked',
        'true',
      ),
    )
    await user.click(screen.getByRole('switch', { name: 'Show profile' }))
    expect(screen.queryByRole('button', { name: /^Profile/ })).toBeNull()
    expect(calls.at(-1)).toMatchObject({
      method: 'PATCH',
      url: '/api/settings',
      body: { show_profile: false },
    })
  })

  it('Escape leaves a top-bar select, so N works again after a result', async () => {
    const { calls } = fakeServer()
    const { user } = setup()
    await answerCheck(user)
    await screen.findByRole('button', { name: /Next puzzle/ })
    const street = screen.getByRole('combobox', { name: 'Street' })
    street.focus()
    await user.keyboard('n')
    expect(calls.filter((c) => c.method === 'POST' && c.url === '/api/puzzles')).toHaveLength(1)
    await user.keyboard('{Escape}')
    expect(street).not.toHaveFocus()
    await user.keyboard('n')
    await waitFor(() =>
      expect(calls.filter((c) => c.method === 'POST' && c.url === '/api/puzzles')).toHaveLength(2),
    )
  })

  it('every app shortcut with a control has a <kbd> hint and aria-keyshortcuts', async () => {
    fakeServer()
    const { user } = setup()
    await answerCheck(user)
    await screen.findByRole('button', { name: /Next puzzle/ })
    for (const s of SHORTCUTS.filter((x) => x.scope === 'app' && x.id !== 'escape')) {
      const nodes = document.querySelectorAll(`[data-shortcut="${s.id}"]`)
      expect(nodes.length, s.id).toBeGreaterThan(0)
      for (const node of nodes) {
        expect(node.getAttribute('aria-keyshortcuts'), s.id).toBe(s.aria)
        expect(s.keys, s.id).toContain(node.querySelector('kbd')?.textContent)
      }
    }
  })

  describe('pages', () => {
    const puzzlePosts = (calls: Call[]) =>
      calls.filter((c) => c.method === 'POST' && c.url === '/api/puzzles')

    it('Progress in the top bar switches the URL and shows the page', async () => {
      fakeServer()
      const { user } = setup()
      await screen.findByRole('textbox', { name: 'Equity' })
      await user.click(screen.getByRole('link', { name: 'Progress' }))
      expect(window.location.pathname).toBe('/progress')
      expect(await screen.findByTestId('progress-totals')).toBeVisible()
      expect(screen.getByRole('link', { name: 'Progress' })).toHaveAttribute('aria-current', 'page')
      // the play area is hidden, not gone, and the puzzle controls are off the bar
      expect(screen.queryByRole('textbox', { name: 'Equity' })).toBeNull()
      expect(screen.queryByRole('button', { name: 'New puzzle' })).toBeNull()
    })

    it('back returns to the same puzzle, half-entered answer kept, with no new puzzle', async () => {
      const { calls } = fakeServer()
      const { user } = setup()
      const equity = await screen.findByRole('textbox', { name: 'Equity' })
      await user.type(equity, '37')
      await user.click(screen.getByRole('link', { name: 'Progress' }))
      await screen.findByTestId('progress-totals')
      act(() => {
        window.history.back()
      })
      await waitFor(() => expect(window.location.pathname).toBe('/'))
      expect(screen.getByRole('textbox', { name: 'Equity' })).toHaveValue('37')
      expect(puzzlePosts(calls)).toHaveLength(1)
      expect(screen.queryByTestId('progress-totals')).toBeNull()
    })

    it('landing on /progress loads no puzzle until Puzzles is clicked', async () => {
      window.history.replaceState(null, '', '/progress')
      const { calls } = fakeServer()
      const { user } = setup()
      await screen.findByTestId('progress-totals')
      await waitFor(() => expect(calls.some((c) => c.url === '/api/settings')).toBe(true))
      expect(calls.filter((c) => c.url.startsWith('/api/puzzles'))).toEqual([])
      await user.click(screen.getByRole('link', { name: 'Puzzles' }))
      expect(await screen.findByRole('textbox', { name: 'Equity' })).toBeVisible()
      expect(
        calls.filter((c) => c.url.startsWith('/api/puzzles')).map((c) => `${c.method} ${c.url}`),
      ).toEqual(['GET /api/puzzles/current', 'POST /api/puzzles'])
    })

    it('shortcuts are off on Progress and back on afterwards', async () => {
      const { calls } = fakeServer()
      const { user } = setup()
      await screen.findByRole('textbox', { name: 'Equity' })
      await user.keyboard('{Escape}')
      await user.click(screen.getByRole('link', { name: 'Progress' }))
      await screen.findByTestId('progress-totals')
      ;(document.activeElement as HTMLElement | null)?.blur()
      await user.keyboard('x')
      await user.keyboard('n')
      await user.keyboard('?')
      expect(screen.queryByText(/Skip this puzzle\?/)).toBeNull()
      expect(screen.queryByRole('dialog')).toBeNull()
      await user.click(screen.getByRole('link', { name: 'Puzzles' }))
      expect(screen.getByRole('button', { name: /^Check/ })).toHaveAttribute(
        'aria-pressed',
        'false',
      )
      expect(puzzlePosts(calls)).toHaveLength(1)
      // and they work again here
      ;(document.activeElement as HTMLElement | null)?.blur()
      await user.keyboard('x')
      expect(screen.getByRole('button', { name: /^Check/ })).toHaveAttribute('aria-pressed', 'true')
    })

    it('the help button still opens the overlay on Progress', async () => {
      fakeServer()
      const { user } = setup()
      await screen.findByRole('textbox', { name: 'Equity' })
      await user.click(screen.getByRole('link', { name: 'Progress' }))
      await screen.findByTestId('progress-totals')
      await user.click(screen.getByRole('button', { name: 'Keyboard shortcuts help' }))
      expect(screen.getByRole('dialog')).toBeVisible()
    })

    it('modified clicks on the nav are left to the browser', async () => {
      fakeServer()
      setup()
      await screen.findByRole('textbox', { name: 'Equity' })
      fireEvent.click(screen.getByRole('link', { name: 'Progress' }), { ctrlKey: true })
      expect(window.location.pathname).toBe('/')
    })

    it('a 422 for the time zone retries once with UTC and shows the UTC note', async () => {
      const seen: string[] = []
      fakeServer({
        stats: (tz) => {
          seen.push(tz)
          return tz === 'UTC'
            ? {
                status: 200,
                body: {
                  ...statsFixture(),
                  days: { ...statsFixture().days, goal: settingsFixture().daily_goal },
                },
              }
            : { status: 422, body: { detail: 'unknown time zone' } }
        },
      })
      // a zone other than UTC, whatever the machine's own
      const spy = vi
        .spyOn(Intl, 'DateTimeFormat')
        .mockImplementation(
          () => ({ resolvedOptions: () => ({ timeZone: 'Mars/Olympus' }) }) as Intl.DateTimeFormat,
        )
      window.history.replaceState(null, '', '/progress')
      setup()
      expect(await screen.findByTestId('utc-note')).toBeVisible()
      expect(seen).toEqual(['Mars/Olympus', 'UTC'])
      spy.mockRestore()
    })

    it('saves the daily goal through the settings and fetches the stats again', async () => {
      window.history.replaceState(null, '', '/progress')
      const { calls } = fakeServer()
      const { user } = setup()
      await screen.findByTestId('progress-totals')
      const input = await screen.findByRole('spinbutton', { name: 'Puzzles per day' })
      await user.clear(input)
      await user.type(input, '25{Enter}')
      await waitFor(() =>
        expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
          { method: 'PATCH', url: '/api/settings', body: { daily_goal: 25 } },
        ]),
      )
      await waitFor(() =>
        expect(calls.filter((c) => c.url.startsWith('/api/stats'))).toHaveLength(2),
      )
    })
  })

  describe('history: replay and stored results', () => {
    const first = () => historyFixture().items[0]!

    it('Replay switches to Puzzles with that puzzle, the practice note, and no new puzzle', async () => {
      const { calls } = fakeServer()
      const { user } = setup()
      await screen.findByRole('textbox', { name: 'Equity' })
      await user.click(screen.getByRole('link', { name: 'Progress' }))
      await screen.findByTestId('history')
      const replay = (await screen.findAllByRole('button', { name: /^Replay puzzle from / }))[0]!
      await user.click(replay)
      expect(window.location.pathname).toBe('/')
      expect(await screen.findByTestId('practice-note')).toHaveTextContent(
        "Practice — this attempt won't count toward your stats.",
      )
      expect(screen.getByRole('textbox', { name: 'Equity' })).toHaveValue('')
      expect(
        calls.some((c) => c.method === 'GET' && c.url === `/api/puzzles/${first().puzzle_id}`),
      ).toBe(true)
      expect(calls.filter((c) => c.method === 'POST' && c.url === '/api/puzzles')).toHaveLength(1)
    })

    it('Replay from a landing on /progress is not replaced by a first load', async () => {
      window.history.replaceState(null, '', '/progress')
      const { calls } = fakeServer()
      const { user } = setup()
      await user.click((await screen.findAllByRole('button', { name: /^Replay puzzle from / }))[0]!)
      expect(await screen.findByTestId('practice-note')).toBeVisible()
      await waitFor(() => expect(screen.getByRole('textbox', { name: 'Equity' })).toBeVisible())
      expect(calls.filter((c) => c.url.startsWith('/api/puzzles') && c.method === 'POST')).toEqual(
        [],
      )
      expect(calls.some((c) => c.url === '/api/puzzles/current')).toBe(false)
    })

    it('Result shows the stored result and focuses Next puzzle, which loads a new puzzle', async () => {
      const { calls } = fakeServer()
      const { user } = setup()
      await screen.findByRole('textbox', { name: 'Equity' })
      await user.click(screen.getByRole('link', { name: 'Progress' }))
      const result = (
        await screen.findAllByRole('button', { name: /^Result of the attempt from / })
      )[0]!
      await user.click(result)
      expect(window.location.pathname).toBe('/')
      expect(await screen.findByRole('region', { name: 'Result' })).toBeVisible()
      expect(
        calls.some((c) => c.method === 'GET' && c.url === `/api/attempts/${first().attempt_id}`),
      ).toBe(true)
      const next = screen.getByRole('button', { name: /Next puzzle/ })
      await waitFor(() => expect(next).toHaveFocus())
      await user.click(next)
      expect(await screen.findByRole('textbox', { name: 'Equity' })).toBeVisible()
      expect(calls.filter((c) => c.method === 'POST' && c.url === '/api/puzzles')).toHaveLength(2)
    })

    it('a failed open shows the error banner with Retry on the Puzzles page', async () => {
      fakeServer()
      const { user } = setup()
      await screen.findByRole('textbox', { name: 'Equity' })
      await user.click(screen.getByRole('link', { name: 'Progress' }))
      const replay = (await screen.findAllByRole('button', { name: /^Replay puzzle from / }))[0]!
      const real = globalThis.fetch
      vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) =>
        /^\/api\/puzzles\/\d+$/.test(String(input))
          ? new Response(JSON.stringify({ detail: 'puzzle not found' }), {
              status: 404,
              headers: { 'Content-Type': 'application/json' },
            })
          : real(input, init),
      )
      await user.click(replay)
      expect(await screen.findByRole('alert')).toHaveTextContent("isn't stored")
      expect(screen.getByRole('button', { name: 'Retry' })).toBeVisible()
    })
  })
})
