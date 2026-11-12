import { StrictMode } from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AttemptResult, PuzzleView } from '../api/types'
import { cardName } from '../lib/cards'
import { SHORTCUTS } from '../lib/shortcuts'
import { attemptFixture, puzzleFixture, settingsFixture } from '../test/fixture'
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
function fakeServer(opts: { puzzles?: PuzzleView[]; attempt?: AttemptResult } = {}) {
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
})
