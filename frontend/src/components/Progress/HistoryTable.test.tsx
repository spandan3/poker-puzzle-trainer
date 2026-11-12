import { StrictMode } from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { HistoryPage } from '../../api/types'
import { historyFixture } from '../../test/fixture'
import type { HistoryApi } from './HistoryTable'
import { HistoryTable } from './HistoryTable'

const PROFILES = [
  { key: 'lag', label: 'Loose-aggressive' },
  { key: 'nit', label: 'Nit' },
]

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function setup(getHistory: HistoryApi['getHistory'] = vi.fn(async () => historyFixture())) {
  const user = userEvent.setup()
  const onReplay = vi.fn()
  const onResult = vi.fn()
  const api = { getHistory: vi.mocked(getHistory) }
  render(
    <StrictMode>
      <HistoryTable api={api} profiles={PROFILES} onReplay={onReplay} onResult={onResult} />
    </StrictMode>,
  )
  return { user, api, onReplay, onResult }
}

const rows = () => within(screen.getByRole('table')).getAllByRole('row').slice(1)

/** A page whose rows are the fixture's, retitled so the page is recognisable. */
function pageOf(total: number, mark: number, n = 25): HistoryPage {
  const base = historyFixture()
  return {
    total,
    items: Array.from({ length: n }, (_, i) => ({
      ...base.items[i % base.items.length]!,
      attempt_id: mark * 1000 + i,
    })),
  }
}

describe('HistoryTable', () => {
  it('loads once under StrictMode: 25 per page, nothing filtered', async () => {
    const { api } = setup()
    await screen.findByRole('table')
    expect(api.getHistory).toHaveBeenCalledTimes(1)
    expect(api.getHistory).toHaveBeenCalledWith({
      limit: 25,
      offset: 0,
      first_only: false,
      street: null,
      verdict: null,
      action_kind: null,
      profile: null,
    })
  })

  it('shows the columns, one row per attempt, and the range text', async () => {
    setup()
    await screen.findByRole('table')
    const heads = within(screen.getByRole('table'))
      .getAllByRole('columnheader')
      .map((h) => h.textContent)
    expect(heads.slice(0, 8)).toEqual([
      'Date',
      'Street',
      'Villain',
      'Your play',
      'Best',
      'Verdict',
      'EV lost',
      'Equity error',
    ])
    const fixture = historyFixture()
    expect(rows()).toHaveLength(fixture.items.length)
    expect(screen.getByTestId('history-range')).toHaveTextContent(
      `1–${fixture.items.length} of ${fixture.total}`,
    )
  })

  it('formats a row: labels, verdict, EV lost in bb, equity error in pts', async () => {
    const page = structuredClone(historyFixture())
    page.items = [
      {
        ...page.items[0]!,
        street: 'turn',
        profile: 'nit',
        chosen_label: 'bet 14',
        best_label: 'bet 100%',
        verdict: 'mistake',
        ev_loss_bb: 1.256,
        equity_error: 0.0421,
        created_at: '2026-11-12T12:00:00Z',
      },
    ]
    setup(vi.fn(async () => ({ ...page, total: 1 })))
    const row = (await screen.findAllByRole('row'))[1]!
    expect(row).toHaveTextContent('Turn')
    expect(row).toHaveTextContent('Nit')
    expect(row).toHaveTextContent('Bet 7 bb')
    expect(row).toHaveTextContent('Bet pot')
    expect(row).toHaveTextContent('Mistake')
    expect(row).toHaveTextContent('1.26 bb')
    expect(row).toHaveTextContent('4.2 pts')
    expect(within(row).queryByText('Practice')).toBeNull()
  })

  it('marks retries with a Practice badge', async () => {
    setup()
    await screen.findByRole('table')
    const fixture = historyFixture()
    const retries = fixture.items.filter((i) => !i.is_first).length
    expect(retries).toBeGreaterThan(0)
    expect(screen.getAllByText('Practice')).toHaveLength(retries)
  })

  it('every row has real Replay and Result buttons that name the row and call back', async () => {
    const { user, onReplay, onResult } = setup()
    await screen.findByRole('table')
    const first = rows()[0]!
    const replay = within(first).getByRole('button', { name: /^Replay puzzle from .+, [\w-]+$/ })
    const result = within(first).getByRole('button', { name: /^Result of the attempt from /i })
    const item = historyFixture().items[0]!
    await user.click(replay)
    expect(onReplay).toHaveBeenCalledWith(item.puzzle_id)
    await user.click(result)
    expect(onResult).toHaveBeenCalledWith(item.attempt_id)
    expect(screen.getAllByRole('button', { name: /^Replay puzzle/ })).toHaveLength(rows().length)
  })

  it('a filter change sends its query parameters and resets to page 1', async () => {
    const getHistory = vi.fn(async () => pageOf(60, 1))
    const { user, api } = setup(getHistory)
    await screen.findByRole('table')
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() =>
      expect(api.getHistory).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25 })),
    )
    await user.selectOptions(screen.getByLabelText('Street'), 'river')
    await waitFor(() =>
      expect(api.getHistory).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 0, street: 'river' }),
      ),
    )
    await user.selectOptions(screen.getByLabelText('Verdict'), 'blunder')
    await user.selectOptions(screen.getByLabelText('Action'), 'raise')
    await user.selectOptions(screen.getByLabelText('Villain'), 'nit')
    await user.click(screen.getByRole('checkbox', { name: 'First attempts only' }))
    await waitFor(() =>
      expect(api.getHistory).toHaveBeenLastCalledWith({
        limit: 25,
        offset: 0,
        first_only: true,
        street: 'river',
        verdict: 'blunder',
        action_kind: 'raise',
        profile: 'nit',
      }),
    )
  })

  it('pages with Previous and Next, "x–y of n"', async () => {
    const getHistory = vi.fn(async (p?: { offset?: number }) =>
      p?.offset === 50 ? pageOf(60, 3, 10) : pageOf(60, 1 + (p?.offset ?? 0) / 25),
    )
    const { user } = setup(getHistory)
    await screen.findByRole('table')
    const range = screen.getByTestId('history-range')
    expect(range).toHaveTextContent('1–25 of 60')
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(range).toHaveTextContent('26–50 of 60'))
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(range).toHaveTextContent('51–60 of 60'))
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Previous' }))
    await waitFor(() => expect(range).toHaveTextContent('26–50 of 60'))
  })

  it('a slow older response never overwrites a newer one', async () => {
    const slow = deferred<HistoryPage>()
    const getHistory = vi.fn((p?: { street?: string | null }) =>
      p?.street === 'flop' ? slow.promise : Promise.resolve(pageOf(p?.street ? 1 : 99, 1, 1)),
    )
    const { user } = setup(getHistory)
    await screen.findByRole('table')
    await user.selectOptions(screen.getByLabelText('Street'), 'flop') // slow
    await user.selectOptions(screen.getByLabelText('Street'), 'river') // fast, newer
    await waitFor(() => expect(screen.getByTestId('history-range')).toHaveTextContent('1–1 of 1'))
    slow.resolve(pageOf(77, 2, 1))
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.getByTestId('history-range')).toHaveTextContent('1–1 of 1')
  })

  it('shows loading first, then an error with Retry, and Retry loads again', async () => {
    const getHistory = vi
      .fn<HistoryApi['getHistory']>()
      .mockRejectedValueOnce(new ApiError(500, 'boom'))
      .mockResolvedValue(historyFixture())
    const { user } = setup(getHistory)
    expect(screen.getByRole('status')).toHaveTextContent('Loading')
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load your history")
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('table')).toBeVisible()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('says so when nothing matches', async () => {
    setup(vi.fn(async () => ({ items: [], total: 0 })))
    expect(await screen.findByText('No attempts match these filters.')).toBeVisible()
    expect(screen.queryByRole('table')).toBeNull()
  })
})
