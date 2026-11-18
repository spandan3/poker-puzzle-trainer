import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Mock } from 'vitest'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DecisionReview, HandAnalysis as Analysis, SettingsView } from '../../api/types'
import { explanationLlmFixture, playHandAnalysisFixture, settingsFixture } from '../../test/fixture'
import type { HandAnalysisApi } from './HandAnalysis'
import { HandAnalysis } from './HandAnalysis'

const FULL = playHandAnalysisFixture()

beforeEach(() => window.localStorage.clear())
afterEach(() => window.localStorage.clear())

type Fake = { [K in keyof HandAnalysisApi]: Mock<HandAnalysisApi[K]> }

function fakeApi(analysis: Analysis, over: Partial<Fake> = {}): Fake {
  return {
    getPlayAnalysis: vi.fn<HandAnalysisApi['getPlayAnalysis']>(async () => analysis),
    postPlayDecision: vi.fn<HandAnalysisApi['postPlayDecision']>(async (_id, n) => {
      return FULL.decisions[n] as DecisionReview
    }),
    getPlayExplanation: vi.fn<HandAnalysisApi['getPlayExplanation']>(async () =>
      explanationLlmFixture(),
    ),
    ...over,
  }
}

function setup(analysis: Analysis, settings: Partial<SettingsView> = {}, over: Partial<Fake> = {}) {
  const api = fakeApi(analysis, over)
  const onClose = vi.fn()
  render(
    <HandAnalysis
      handId={FULL.hand_id}
      api={api}
      settings={{ ...settingsFixture(), ...settings }}
      onClose={onClose}
    />,
  )
  return { api, onClose, user: userEvent.setup() }
}

const steps = () => screen.getByRole('list', { name: 'Decisions' })

describe('HandAnalysis', () => {
  it('while loading shows the progress', async () => {
    let release: (() => void) | undefined
    // two stored of four: the third is being analysed
    const stored: Analysis = {
      ...FULL,
      summary: null,
      decisions: [FULL.decisions[0]!, FULL.decisions[1]!, null, null],
    }
    setup(
      stored,
      {},
      {
        postPlayDecision: vi.fn(
          () =>
            new Promise<DecisionReview>((resolve) => {
              release = () => resolve(FULL.decisions[2]!)
            }),
        ),
      },
    )
    expect(await screen.findByText('Analysing decision 3 of 4…')).toBeInTheDocument()
    release?.()
  })

  it('shows the summary with the total EV lost and the worst decision marked', async () => {
    setup(FULL)
    const summary = await screen.findByRole('region', { name: 'Summary' })
    expect(within(summary).getByText(/3\.17 bb/)).toBeInTheDocument()
    const worst = FULL.summary!.worst_index!
    const item = within(steps()).getAllByRole('listitem')[worst]!
    expect(within(item).getByText('Most EV lost')).toBeInTheDocument()
    expect(within(steps()).getAllByText('Most EV lost')).toHaveLength(1)
    // neutral text: no "Worst" label, no verdict tone on the mark
    expect(screen.queryByText('Worst')).toBeNull()
    expect(within(item).getByText('Most EV lost')).not.toHaveAttribute('data-tone')
    expect(within(item).getByText('Most EV lost')).not.toHaveAttribute('data-verdict')
  })

  it('the selected step’s header reads "Decision n · Street" over a grade line with no badge', async () => {
    const { user } = setup(FULL)
    await screen.findByRole('region', { name: 'Summary' })
    await user.click(within(steps()).getAllByRole('button')[1]!)
    const heading = screen.getByRole('heading', { name: 'Decision 2 · Flop' })
    const gradeLine = heading.nextElementSibling as HTMLElement
    expect(gradeLine).toHaveTextContent(/^You: Check · Top EV: /)
    expect(gradeLine.querySelector('[data-tone], [data-verdict]')).toBeNull()
    for (const verdict of ['Best', 'Fine', 'Mistake', 'Blunder']) {
      expect(within(gradeLine).queryByText(verdict)).toBeNull()
    }
  })

  it('the details are not inside a Panel (panels are never nested)', async () => {
    setup(FULL)
    await screen.findByRole('region', { name: 'Summary' })
    const header = screen.getByRole('region', { name: 'Hand analysis' })
    expect(header.contains(screen.getByRole('tablist', { name: 'Details' }))).toBe(false)
    expect(header.contains(screen.getByRole('region', { name: 'Summary' }))).toBe(true)
  })

  it('during a retry the status reads "Retrying…"', async () => {
    const stored: Analysis = { ...FULL, summary: null, decisions: [FULL.decisions[0]!, null] }
    let release: (() => void) | undefined
    const post = vi
      .fn<HandAnalysisApi['postPlayDecision']>()
      .mockRejectedValueOnce(new Error('boom'))
      .mockImplementation(
        () =>
          new Promise<DecisionReview>((resolve) => {
            release = () => resolve(FULL.decisions[1]!)
          }),
      )
    const { user } = setup(stored, {}, { postPlayDecision: post })
    await user.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Retrying…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
    release?.()
  })

  it('reports the view of the selected step to the page', async () => {
    const onView = vi.fn()
    const api = fakeApi(FULL)
    const user = userEvent.setup()
    render(
      <HandAnalysis
        handId={FULL.hand_id}
        api={api}
        settings={settingsFixture()}
        onClose={vi.fn()}
        onView={onView}
      />,
    )
    await screen.findByRole('region', { name: 'Summary' })
    await user.click(within(steps()).getAllByRole('button')[1]!)
    expect(onView).toHaveBeenLastCalledWith(FULL.decisions[1]!.view)
  })

  it('lists each step with its street, action, verdict and EV lost', async () => {
    setup(FULL)
    await screen.findByRole('region', { name: 'Summary' })
    const items = within(steps()).getAllByRole('listitem')
    expect(items).toHaveLength(4)
    expect(items[0]).toHaveTextContent('Pre-flop')
    expect(items[0]).toHaveTextContent('Raise 2.5x')
    expect(items[0]).toHaveTextContent('Best')
    expect(items[3]).toHaveTextContent('River')
    expect(items[3]).toHaveTextContent('Blunder')
    expect(items[3]).toHaveTextContent('1.47 bb')
  })

  it('clicking a step shows its verdict line and the details tabs', async () => {
    const { user } = setup(FULL)
    await screen.findByRole('region', { name: 'Summary' })
    await user.click(within(steps()).getAllByRole('button')[1]!)
    expect(screen.getByText(/^You: Check · Top EV: /)).toBeInTheDocument()
    const tabs = within(screen.getByRole('tablist', { name: 'Details' })).getAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['Why', 'Options', 'Maths', 'Range', 'Hand'])
  })

  it('has no equity guess or range-read score anywhere', async () => {
    const { user } = setup(FULL)
    await screen.findByRole('region', { name: 'Summary' })
    for (const name of ['Why', 'Options', 'Maths', 'Range', 'Hand']) {
      await user.click(screen.getByRole('tab', { name }))
      expect(screen.queryByText(/your guess|you guessed|range read/i)).toBeNull()
    }
  })

  it('the Hand tab shows the bot’s cards, its profile and the showdown', async () => {
    const { user } = setup(FULL)
    await screen.findByRole('region', { name: 'Summary' })
    await user.click(screen.getByRole('tab', { name: 'Hand' }))
    const bot = screen.getByRole('group', { name: "Villain's hand" })
    expect(within(bot).getAllByRole('img')).toHaveLength(2)
    expect(screen.getByText('LAG')).toBeInTheDocument()
    expect(screen.getByText('Villain wins: High card vs Pair')).toBeInTheDocument()
    expect(screen.getByText(FULL.judged_on_range_note)).toBeInTheDocument()
  })

  it('words the judged-on note for a fold without "this run-out", as the result page does', async () => {
    const last = FULL.decisions.length - 1
    const folded: Analysis = {
      ...FULL,
      decisions: FULL.decisions.map((d, i) => (i === last ? { ...d!, chosen_label: 'fold' } : d)),
    }
    setup(folded)
    await screen.findByRole('region', { name: 'Summary' })
    expect(screen.getByText("Graded against Villain's whole range.")).toBeInTheDocument()
    expect(screen.queryByText(/this run-out/)).toBeNull()
  })

  it('keeps the API note when Hero did not fold', async () => {
    setup(FULL)
    await screen.findByRole('region', { name: 'Summary' })
    expect(screen.getByText(FULL.judged_on_range_note)).toBeInTheDocument()
  })

  it('the Hand tab for a hand that ended in a fold shows the bot’s cards and profile', async () => {
    const folded: Analysis = {
      ...FULL,
      reveal: { ...FULL.reveal, showdown: null, board: FULL.reveal.board.slice(0, 3) },
    }
    const { user } = setup(folded)
    await screen.findByRole('region', { name: 'Summary' })
    await user.click(screen.getByRole('tab', { name: 'Hand' }))
    expect(
      within(screen.getByRole('group', { name: "Villain's hand" })).getAllByRole('img'),
    ).toHaveLength(2)
    expect(screen.getByText('LAG')).toBeInTheDocument()
    expect(screen.getByText(/no showdown/i)).toBeInTheDocument()
  })

  it('a not-graded step says why and has no details', async () => {
    const notGraded: DecisionReview = {
      ...FULL.decisions[1]!,
      status: 'not_graded',
      reason: 'the range tracker lost the thread',
      grade: null,
      options: [],
      simplifications: [],
      categories: null,
      range_steps: [],
      chosen_label: null,
      explanation: null,
    }
    const { user } = setup({
      ...FULL,
      summary: { ev_loss_bb: 1, worst_index: 3 },
      decisions: [FULL.decisions[0]!, notGraded, FULL.decisions[2]!, FULL.decisions[3]!],
    })
    await screen.findByRole('region', { name: 'Summary' })
    expect(within(steps()).getAllByRole('listitem')[1]).toHaveTextContent(
      'Not graded: the range tracker lost the thread',
    )
    await user.click(within(steps()).getAllByRole('button')[1]!)
    expect(screen.queryByRole('tablist')).toBeNull()
    expect(
      screen.getAllByText('Not graded: the range tracker lost the thread').length,
    ).toBeGreaterThan(0)
  })

  it('says so when nothing was graded, and when nothing lost EV', async () => {
    const notGraded = (d: DecisionReview): DecisionReview => ({
      ...d,
      status: 'not_graded',
      reason: 'no range',
      grade: null,
      options: [],
      simplifications: [],
      categories: null,
      range_steps: [],
      chosen_label: null,
      explanation: null,
    })
    setup({
      ...FULL,
      summary: { ev_loss_bb: 0, worst_index: null },
      decisions: FULL.decisions.map((d) => notGraded(d as DecisionReview)),
    })
    await screen.findByRole('region', { name: 'Summary' })
    expect(screen.getByText('No decision could be graded.')).toBeInTheDocument()
    expect(screen.queryByText('No decision lost EV.')).toBeNull()
    cleanup()
    setup({ ...FULL, summary: { ev_loss_bb: 0, worst_index: null } })
    await screen.findByRole('region', { name: 'Summary' })
    expect(screen.getByText('No decision lost EV.')).toBeInTheDocument()
    expect(screen.queryByText('No decision could be graded.')).toBeNull()
  })

  it('says when the Villain model has changed', async () => {
    setup({ ...FULL, model_changed: true })
    expect(await screen.findByText('Villain model has changed since this hand')).toBeInTheDocument()
  })

  it('does not say it when the model is the same', async () => {
    setup(FULL)
    await screen.findByRole('region', { name: 'Summary' })
    expect(screen.queryByText(/model has changed/)).toBeNull()
  })

  it('the Why tab asks the play explanation route when a model is on', async () => {
    const { api, user } = setup(FULL, {
      llm_status: 'ready',
      llm_model: 'llama3.2:3b',
      llm_detail: null,
    })
    await screen.findByRole('region', { name: 'Summary' })
    await user.click(within(steps()).getAllByRole('button')[2]!)
    await waitFor(() => expect(api.getPlayExplanation).toHaveBeenCalled())
    // the worst step (3) opens first; picking step 2 asks for its own explanation
    await waitFor(() =>
      expect(api.getPlayExplanation).toHaveBeenCalledWith(FULL.hand_id, 2, expect.anything()),
    )
    expect(api.getPlayExplanation).toHaveBeenCalledWith(FULL.hand_id, 3, expect.anything())
  })

  it('asks nothing of the model when it is off', async () => {
    const { api } = setup(FULL, { llm_status: 'off' })
    await screen.findByRole('region', { name: 'Summary' })
    expect(api.getPlayExplanation).not.toHaveBeenCalled()
  })

  it('an analysis that was stored is shown without posting', async () => {
    const { api } = setup(FULL)
    await screen.findByRole('region', { name: 'Summary' })
    expect(api.postPlayDecision).not.toHaveBeenCalled()
  })

  it('a hand with no decision says so', async () => {
    setup({ ...FULL, decisions: [], summary: null })
    expect(await screen.findByText('You made no decision in this hand.')).toBeInTheDocument()
  })

  it('a failed step shows the error and Retry continues', async () => {
    const stored: Analysis = { ...FULL, summary: null, decisions: [FULL.decisions[0]!, null] }
    const post = vi
      .fn<HandAnalysisApi['postPlayDecision']>()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValue(FULL.decisions[1]!)
    const get = vi
      .fn<HandAnalysisApi['getPlayAnalysis']>()
      .mockResolvedValueOnce(stored)
      .mockResolvedValue({ ...FULL, decisions: FULL.decisions.slice(0, 2) })
    const { user } = setup(stored, {}, { postPlayDecision: post, getPlayAnalysis: get })
    await user.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('region', { name: 'Summary' })).toBeInTheDocument()
  })

  it('Close calls onClose', async () => {
    const { onClose, user } = setup(FULL)
    await user.click(await screen.findByRole('button', { name: 'Close analysis' }))
    expect(onClose).toHaveBeenCalled()
  })
})
