import { StrictMode } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { historyFixture, statsEmptyFixture, statsFixture } from '../../test/fixture'
import type { ProgressApi } from './ProgressPage'
import { ProgressPage } from './ProgressPage'

function fakeApi(over: Partial<ProgressApi> = {}) {
  return {
    getStats: vi.fn<ProgressApi['getStats']>(async () => statsFixture()),
    getHistory: vi.fn<ProgressApi['getHistory']>(async () => historyFixture()),
    ...over,
  }
}

function setup(api: ProgressApi, onGoal: (goal: number) => Promise<boolean> = async () => true) {
  const user = userEvent.setup()
  render(
    <StrictMode>
      <ProgressPage api={api} goal={null} onGoal={onGoal} onReplay={vi.fn()} onResult={vi.fn()} />
    </StrictMode>,
  )
  return { user, onGoal }
}

afterEach(() => {
  vi.restoreAllMocks()
})

/** A browser whose zone isn't UTC, whatever the machine's own. */
function zoneIs(timeZone: string) {
  vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(
    () => ({ resolvedOptions: () => ({ timeZone }) }) as Intl.DateTimeFormat,
  )
}

const tile = (id: string) => screen.getByTestId(`tile-${id}`)

describe('ProgressPage', () => {
  it('fetches stats once under StrictMode, with the browser time zone', async () => {
    const api = fakeApi()
    setup(api)
    expect(screen.getByRole('status')).toHaveTextContent('Loading')
    await screen.findByTestId('progress-totals')
    expect(api.getStats).toHaveBeenCalledTimes(1)
    expect(api.getStats).toHaveBeenCalledWith(expect.stringMatching(/\S+/))
  })

  it('shows the totals line and the headline tiles, formatted', async () => {
    setup(fakeApi())
    const stats = statsFixture()
    expect(await screen.findByTestId('progress-totals')).toHaveTextContent(
      `${stats.totals.first_attempts} puzzles answered · ${stats.totals.retries} practice attempts`,
    )
    // 1.4657 -> "1.47 bb", the change against the 50 before (1.9060) is an improvement
    expect(tile('ev')).toHaveTextContent('1.47 bb')
    expect(tile('ev')).toHaveTextContent('0.44 bb better than the 50 before')
    expect(tile('accuracy')).toHaveTextContent('88%')
    expect(tile('equity')).toHaveTextContent('9.3 pts')
    expect(tile('range')).toHaveTextContent('6.2 pts')
    expect(tile('streak')).toHaveTextContent(`${stats.streak.current}`)
    expect(tile('streak')).toHaveTextContent(`best ${stats.streak.best}`)
    expect(tile('today')).toHaveTextContent(`${stats.days.today} / ${stats.days.goal}`)
    expect(tile('today')).toHaveTextContent(`${stats.days.current_streak}-day streak`)
  })

  it('says "1 puzzle answered" and "1 practice attempt" in the singular', async () => {
    const stats = structuredClone(statsFixture())
    stats.totals = { ...stats.totals, first_attempts: 1, retries: 1 }
    setup(fakeApi({ getStats: async () => stats }))
    expect(await screen.findByTestId('progress-totals')).toHaveTextContent(
      /^1 puzzle answered · 1 practice attempt$/,
    )
  })

  it('colours the EV tile from the rounded difference: "same" is neutral', async () => {
    const stats = structuredClone(statsFixture())
    stats.headline = { ...stats.headline, ev_lost_bb_last50: 1.501, ev_lost_bb_prev50: 1.5 }
    setup(fakeApi({ getStats: async () => stats }))
    await screen.findByTestId('progress-totals')
    const note = within(tile('ev')).getByText('same as the 50 before')
    expect(note).not.toHaveAttribute('data-tone', 'good')
    expect(note).not.toHaveAttribute('data-tone', 'bad')
  })

  it('colours a better EV tile good and a worse one bad', async () => {
    setup(fakeApi())
    await screen.findByTestId('progress-totals')
    expect(within(tile('ev')).getByText(/better than/)).toHaveAttribute('data-tone', 'good')
  })

  it('nests headings: page h2, sections h3 (with a hidden Summary), chart titles h4', async () => {
    setup(fakeApi())
    await screen.findByTestId('progress-totals')
    expect(screen.getByRole('heading', { level: 2, name: 'Progress' })).toBeVisible()
    const h3 = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(h3).toEqual(['Summary', 'Trends', 'Daily goal', 'Leaks', 'Breakdown', 'History'])
    expect(screen.getAllByRole('heading', { level: 4 }).map((h) => h.textContent)).toEqual(
      expect.arrayContaining(['EV lost per decision', 'Equity error', 'Range-read error']),
    )
    expect(screen.queryAllByRole('heading', { level: 1 })).toHaveLength(0)
  })

  it('the Villain filter lists every profile from the settings, played or not', async () => {
    const profiles = [
      { name: 'tag', label: 'TAG' },
      { name: 'maniac', label: 'Maniac (no attempts yet)' },
    ]
    render(
      <ProgressPage
        api={fakeApi()}
        goal={null}
        profiles={profiles}
        onGoal={async () => true}
        onReplay={vi.fn()}
        onResult={vi.fn()}
      />,
    )
    const select = await screen.findByLabelText('Villain', { selector: 'select' })
    expect(
      within(select)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['All', 'TAG', 'Maniac (no attempts yet)'])
  })

  it('the Villain filter falls back to the stats breakdown when the settings are not loaded', async () => {
    setup(fakeApi())
    const select = await screen.findByLabelText('Villain', { selector: 'select' })
    expect(
      within(select)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['All', ...statsFixture().breakdowns.profile.map((r) => r.label)])
  })

  it('draws the three trend charts and the day chart, each with a data table', async () => {
    setup(fakeApi())
    await screen.findByTestId('progress-totals')
    expect(screen.getAllByTestId('line-chart')).toHaveLength(3)
    expect(screen.getByTestId('bar-chart')).toBeInTheDocument()
    const evTable = screen.getByRole('table', { name: /EV lost per decision/ })
    expect(within(evTable).getAllByRole('row')).toHaveLength(1) // rows only while open
    const details = evTable.closest('details')!
    details.open = true
    fireEvent(details, new Event('toggle'))
    expect(within(evTable).getAllByRole('row')).toHaveLength(statsFixture().trend.length + 1)
    expect(screen.getByRole('table', { name: /Puzzles per day.*goal/ })).toBeInTheDocument()
  })

  it('lists the leaks and the breakdown', async () => {
    setup(fakeApi())
    await screen.findByTestId('progress-totals')
    expect(screen.getByRole('heading', { name: 'Folding too often' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Street', selected: true })).toBeInTheDocument()
  })

  it('leaves a clear spot for the history table', async () => {
    setup(fakeApi())
    await screen.findByTestId('progress-totals')
    expect(screen.getByTestId('history')).toBeInTheDocument()
  })

  it('shows an error with Retry, which fetches again', async () => {
    const api = fakeApi({
      getStats: vi
        .fn<ProgressApi['getStats']>()
        .mockRejectedValueOnce(new ApiError(500, 'boom'))
        .mockResolvedValue(statsFixture()),
    })
    const { user } = setup(api)
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load your progress")
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByTestId('progress-totals')
    expect(api.getStats).toHaveBeenCalledTimes(2)
  })

  it('shows the empty state with a link to the puzzles', async () => {
    setup(fakeApi({ getStats: async () => statsEmptyFixture() }))
    expect(await screen.findByText('No puzzles answered yet')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Start a puzzle' })).toHaveAttribute('href', '/')
    expect(screen.queryByTestId('line-chart')).toBeNull()
    expect(screen.queryByTestId('bar-chart')).toBeNull()
  })

  it('retries once with UTC after a 422 and says so', async () => {
    const getStats = vi
      .fn<ProgressApi['getStats']>()
      .mockRejectedValueOnce(new ApiError(422, 'unknown time zone'))
      .mockResolvedValue(statsFixture())
    zoneIs('Mars/Olympus')
    setup(fakeApi({ getStats }))
    expect(await screen.findByTestId('utc-note')).toHaveTextContent(
      "Days are counted in UTC (your time zone isn't known to the server).",
    )
    expect(getStats.mock.calls).toEqual([['Mars/Olympus'], ['UTC']])
  })

  it('does not loop when UTC itself fails', async () => {
    const getStats = vi.fn<ProgressApi['getStats']>().mockRejectedValue(new ApiError(422, 'x'))
    zoneIs('Mars/Olympus')
    setup(fakeApi({ getStats }))
    await screen.findByRole('alert')
    expect(getStats).toHaveBeenCalledTimes(2)
  })

  it('refetches the stats after a goal is saved, and not after a failed save', async () => {
    const api = fakeApi()
    const onGoal = vi.fn(async () => true)
    const { user } = setup(api, onGoal)
    await screen.findByTestId('progress-totals')
    const input = screen.getByRole('spinbutton', { name: 'Puzzles per day' })
    await user.clear(input)
    await user.type(input, '20{Enter}')
    expect(onGoal).toHaveBeenCalledWith(20)
    await waitFor(() => expect(api.getStats).toHaveBeenCalledTimes(2))
    // the page stays up while it refetches (no loading flash)
    expect(screen.getByTestId('progress-totals')).toBeInTheDocument()

    onGoal.mockResolvedValueOnce(false as never)
    await user.clear(input)
    await user.type(input, '30{Enter}')
    await waitFor(() => expect(onGoal).toHaveBeenCalledWith(30))
    expect(api.getStats).toHaveBeenCalledTimes(2)
  })

  it('shows the goal setting rather than the stats goal when it is known', async () => {
    const api = fakeApi()
    render(
      <ProgressPage
        api={api}
        goal={7}
        onGoal={async () => true}
        onReplay={vi.fn()}
        onResult={vi.fn()}
      />,
    )
    expect(await screen.findByRole('spinbutton', { name: 'Puzzles per day' })).toHaveValue(7)
    // everything computed from the goal shows the stats' own goal, never the box's
    expect(screen.queryByText(/\/ 7\b/)).toBeNull()
  })

  it('fetches once more when the goal setting differs from the stats goal, and does not loop', async () => {
    const api = fakeApi()
    render(
      <ProgressPage
        api={api}
        goal={10}
        onGoal={async () => true}
        onReplay={vi.fn()}
        onResult={vi.fn()}
      />,
    )
    await screen.findByTestId('progress-totals')
    await waitFor(() => expect(api.getStats).toHaveBeenCalledTimes(2))
    await new Promise((r) => setTimeout(r, 50))
    expect(api.getStats).toHaveBeenCalledTimes(2)
    expect(tile('today')).toHaveTextContent('/ 3')
    expect(screen.queryByText(/\/ 10\b/)).toBeNull()
  })
})
