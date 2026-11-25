import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PlaySessionView, SettingsView } from '../../api/types'
import type { PlayFlow, PlayState } from '../../app/usePlayFlow'
import { formatBb } from '../../lib/format'
import { signedBbFromBb } from '../../lib/play'
import {
  play5SessionFixture,
  playHandAnalysisFixture,
  playHandsFixture,
  playSessionFixture,
  playSessionsFixture,
  settingsFixture,
} from '../../test/fixture'
import type { PlayPageApi } from './PlayPage'
import { PlayPage } from './PlayPage'
import { StartPanel } from './StartPanel'

const FACE_UP = { name: / of (spades|hearts|diamonds|clubs)$/ }

function flowFor(session: PlaySessionView | null, over: Partial<PlayFlow> = {}): PlayFlow {
  const total = session?.hand?.table.history.length ?? 0
  const shownCount = over.shownCount ?? total
  const revealing = shownCount < total
  const over_ = session?.hand?.status === 'complete' && !revealing
  const state: PlayState = !session
    ? { kind: 'idle' }
    : over_
      ? { kind: 'handOver' }
      : { kind: 'playing' }
  return {
    state,
    session,
    past: playSessionsFixture(),
    shownCount,
    revealing,
    busy: false,
    start: vi.fn(),
    act: vi.fn(),
    nextHand: vi.fn(),
    end: vi.fn(),
    retry: vi.fn(),
    ...over,
  }
}

function setup(
  session: PlaySessionView | null,
  over: Partial<PlayFlow> = {},
  settings: Partial<SettingsView> = {},
  shortcutsOn = false,
) {
  const flow = flowFor(session, over)
  const api = {
    getPlayAnalysis: vi.fn<PlayPageApi['getPlayAnalysis']>(async () => playHandAnalysisFixture()),
    postPlayDecision: vi.fn<PlayPageApi['postPlayDecision']>(),
    getPlayExplanation: vi.fn<PlayPageApi['getPlayExplanation']>(),
    listPlayHands: vi.fn<PlayPageApi['listPlayHands']>(async () => playHandsFixture()),
  }
  render(
    <PlayPage
      flow={flow}
      settings={{ ...settingsFixture(), ...settings }}
      shortcutsOn={shortcutsOn}
      api={api}
    />,
  )
  return { flow, api, user: userEvent.setup() }
}

const hero = () => screen.getByRole('group', { name: /^Hero,/ })
const villain = () => screen.getByRole('group', { name: /^Villain,/ })

describe('PlayPage: a hand in progress', () => {
  it('Hero to act: the table, face-down bot cards, the action panel and the history', () => {
    setup(playSessionFixture('hero_to_act'))
    expect(within(hero()).getAllByRole('img', FACE_UP)).toHaveLength(2)
    expect(within(villain()).getAllByRole('img', { name: 'face-down card' })).toHaveLength(2)
    const panel = screen.getByRole('form', { name: 'Your answer' })
    expect(within(panel).getByRole('button', { name: /^Submit/ })).toBeInTheDocument()
    // no guesses in play
    expect(screen.queryByRole('textbox', { name: 'Equity' })).toBeNull()
    expect(screen.getByText('Hero to act')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Next hand' })).toBeNull()
  })

  it('submitting sends the chosen option to the flow', async () => {
    const { flow, user } = setup(playSessionFixture('hero_to_act'))
    await user.click(screen.getByRole('button', { name: /^Check/ }))
    await user.click(screen.getByRole('button', { name: /^Submit/ }))
    expect(flow.act).toHaveBeenCalledWith({ option: 0 })
  })

  it('during the reveal the panel is disabled and the history ends with Villain to act', () => {
    // the showdown hand after Hero's first action: Hero has raised, the bot has not yet called
    const session = playSessionFixture('hand_over_showdown')
    setup(session, { shownCount: 1 })
    const panel = screen.getByRole('form', { name: 'Your answer' })
    expect(panel).toHaveAttribute('aria-busy', 'true')
    for (const button of within(panel).getAllByRole('button')) {
      expect(
        button.hasAttribute('disabled') || button.getAttribute('aria-disabled') === 'true',
      ).toBe(true)
    }
    expect(screen.getByText('Villain to act')).toBeInTheDocument()
    expect(screen.queryByText('Hero to act')).toBeNull()
    // the table is the frame: the flop has not come yet, and the bot's cards stay down
    expect(screen.getByText('Pot 3.5 bb')).toBeInTheDocument()
    expect(within(villain()).getAllByRole('img', { name: 'face-down card' })).toHaveLength(2)
    // the hand is not over until the reveal is done
    expect(screen.queryByRole('button', { name: 'Next hand' })).toBeNull()
    expect(screen.queryByText(/won/)).toBeNull()
  })

  it('only the entries shown are in the history', () => {
    setup(playSessionFixture('hand_over_showdown'), { shownCount: 2 })
    const history = screen.getByRole('complementary')
    expect(within(history).getAllByRole('listitem')).toHaveLength(2)
  })

  it('shows the profile only when show_profile is on', () => {
    setup(playSessionFixture('hero_to_act'), {}, { show_profile: true })
    expect(screen.getByRole('button', { name: 'Profile LAG' })).toBeInTheDocument()
  })

  it('hides the profile when show_profile is off', () => {
    setup(playSessionFixture('hero_to_act'), {}, { show_profile: false })
    expect(screen.queryByRole('button', { name: 'Profile LAG' })).toBeNull()
  })
})

describe('PlayPage: a finished hand', () => {
  it('by fold: the result line, Next hand and Analyse; the bot keeps its cards down', () => {
    setup(playSessionFixture('hand_over_fold'))
    expect(screen.getByText('You won 1 bb')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Next hand/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyse this hand' })).toBeInTheDocument()
    expect(within(villain()).getAllByRole('img', { name: 'face-down card' })).toHaveLength(2)
    expect(screen.queryByText(/to act/)).toBeNull()
  })

  it('by showdown: the bot’s cards are face up and the hands are named', () => {
    setup(playSessionFixture('hand_over_showdown'))
    expect(screen.getByText('Villain won 2.5 bb at showdown')).toBeInTheDocument()
    expect(within(villain()).getAllByRole('img', FACE_UP)).toHaveLength(2)
    expect(within(villain()).queryByRole('img', { name: 'face-down card' })).toBeNull()
    expect(screen.getByText('You: High card · Villain: Pair')).toBeInTheDocument()
  })

  it('Analyse this hand opens the analysis of the hand just played', async () => {
    const session = playSessionFixture('hand_over_showdown')
    const { api, user } = setup(session)
    await user.click(screen.getByRole('button', { name: 'Analyse this hand' }))
    expect(await screen.findByRole('region', { name: 'Summary' })).toBeInTheDocument()
    expect(api.getPlayAnalysis).toHaveBeenCalledWith(session.hand!.id)
    expect(screen.queryByRole('button', { name: /^Next hand/ })).toBeNull()
  })

  it('closing the analysis returns to the hand-over panel with Next hand', async () => {
    const { flow, user } = setup(playSessionFixture('hand_over_showdown'))
    await user.click(screen.getByRole('button', { name: 'Analyse this hand' }))
    await user.click(await screen.findByRole('button', { name: 'Close analysis' }))
    expect(screen.queryByRole('region', { name: 'Summary' })).toBeNull()
    await user.click(screen.getByRole('button', { name: /^Next hand/ }))
    expect(flow.nextHand).toHaveBeenCalledWith(false)
  })

  it('N does not deal while the analysis is open', async () => {
    const { flow, user } = setup(playSessionFixture('hand_over_showdown'), {}, {}, true)
    await user.click(screen.getByRole('button', { name: 'Analyse this hand' }))
    await screen.findByRole('region', { name: 'Summary' })
    await user.click(screen.getByRole('tab', { name: 'Options' }))
    await user.keyboard('n')
    expect(flow.nextHand).not.toHaveBeenCalled()
  })

  it('the session’s hands list opens any hand of the session', async () => {
    const { api, user } = setup(playSessionFixture('hand_over_showdown'))
    await user.click(screen.getByRole('button', { name: /^Session hands/ }))
    await user.click(await screen.findByRole('button', { name: 'Analyse hand 2' }))
    expect(await screen.findByRole('region', { name: 'Summary' })).toBeInTheDocument()
    expect(api.getPlayAnalysis).toHaveBeenCalledWith(playHandsFixture()[1]!.id)
  })

  it('a hand with no Hero decision has no Analyse button', () => {
    const fold = playSessionFixture('hand_over_fold')
    setup({ ...fold, hand: { ...fold.hand!, decision_count: 0 } })
    expect(screen.queryByRole('button', { name: 'Analyse this hand' })).toBeNull()
  })

  it('Next hand deals without a top-up by default', async () => {
    const { flow, user } = setup(playSessionFixture('hand_over_fold'))
    await user.click(screen.getByRole('button', { name: /^Next hand/ }))
    expect(flow.nextHand).toHaveBeenCalledWith(false)
  })

  it('Top up shows only when can_top_up, and is sent with Next hand', async () => {
    const fold = playSessionFixture('hand_over_fold')
    const { flow, user } = setup({ ...fold, can_top_up: true })
    await user.click(screen.getByRole('checkbox', { name: 'Top up to 100 bb' }))
    await user.click(screen.getByRole('button', { name: /^Next hand/ }))
    expect(flow.nextHand).toHaveBeenCalledWith(true)
  })

  it('no Top up option when it cannot be used', () => {
    setup({ ...playSessionFixture('hand_over_fold'), can_top_up: false })
    expect(screen.queryByRole('checkbox', { name: /Top up/ })).toBeNull()
  })

  it('must_rebuy: the button reads Rebuy and deal', () => {
    setup({ ...playSessionFixture('hand_over_fold'), must_rebuy: true })
    expect(screen.getByRole('button', { name: /^Rebuy and deal/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Next hand/ })).toBeNull()
  })

  it('N deals the next hand when shortcuts are on', async () => {
    const { flow, user } = setup(playSessionFixture('hand_over_fold'), {}, {}, true)
    await user.keyboard('n')
    expect(flow.nextHand).toHaveBeenCalledWith(false)
  })

  it('N does nothing with shortcuts off or while a hand is running', async () => {
    const off = setup(playSessionFixture('hand_over_fold'), {}, {}, false)
    await off.user.keyboard('n')
    expect(off.flow.nextHand).not.toHaveBeenCalled()
    cleanup()
    const running = setup(playSessionFixture('hero_to_act'), {}, {}, true)
    await running.user.keyboard('n')
    expect(running.flow.nextHand).not.toHaveBeenCalled()
  })

  it('Next hand is disabled while a request is in flight', async () => {
    const { flow, user } = setup(playSessionFixture('hand_over_fold'), { busy: true })
    await user.click(screen.getByRole('button', { name: /^Next hand/ }))
    expect(flow.nextHand).not.toHaveBeenCalled()
  })
})

describe('PlayPage: the start panel', () => {
  it('with no session: Start session, the help note and the past sessions', async () => {
    const { flow, user } = setup(null)
    expect(
      screen.getByText(
        'Pre-flop, the bot responds the same way to a 2.5x and a 3x open or 3-bet, and treats an all-in as a jam. There is no limping and no small 4-bet.',
      ),
    ).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Past sessions' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    // net_bb straight from the API, signed: no chips conversion
    expect(rows[1]).toHaveTextContent(signedBbFromBb(playSessionsFixture()[1]!.net_bb))
    expect(rows[1]).toHaveTextContent('−52.5 bb')
    expect(rows[0]).toHaveTextContent('0 bb')
    expect(rows[1]).toHaveTextContent('13')
    await user.click(screen.getByRole('button', { name: 'Start session' }))
    expect(flow.start).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('group', { name: /^Hero,/ })).toBeNull()
  })

  it('no past sessions: no table', () => {
    setup(null, { past: [] })
    expect(screen.queryByRole('table', { name: 'Past sessions' })).toBeNull()
  })

  it('has the page heading and the past sessions as a table with column headers', () => {
    setup(null)
    expect(screen.getByRole('heading', { name: 'Play against a bot' })).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Past sessions' })
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((h) => h.textContent),
    ).toEqual(['Date', 'Profile', 'Hands', 'Net', 'Hands list'])
  })

  it('a new refreshKey reloads an open hand list', async () => {
    const flow = flowFor(null)
    const api = {
      getPlayAnalysis: vi.fn<PlayPageApi['getPlayAnalysis']>(),
      postPlayDecision: vi.fn<PlayPageApi['postPlayDecision']>(),
      getPlayExplanation: vi.fn<PlayPageApi['getPlayExplanation']>(),
      listPlayHands: vi.fn<PlayPageApi['listPlayHands']>(async () => playHandsFixture()),
    }
    const user = userEvent.setup()
    const ui = (refreshKey: number) => (
      <StartPanel
        onStart={vi.fn()}
        busy={false}
        past={flow.past}
        onOpenHand={vi.fn()}
        api={api}
        refreshKey={refreshKey}
      />
    )
    const { rerender } = render(ui(0))
    await user.click(screen.getAllByRole('button', { name: /^Hands of session/ })[0]!)
    await screen.findByRole('table', { name: 'Hands' })
    expect(api.listPlayHands).toHaveBeenCalledTimes(1)
    rerender(ui(1))
    await waitFor(() => expect(api.listPlayHands).toHaveBeenCalledTimes(2))
  })

  it('Start session is disabled while starting', () => {
    setup(null, { busy: true })
    expect(screen.getByRole('button', { name: 'Start session' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
  })
})

describe('PlayPage: past sessions', () => {
  it('a past session’s hands open from the start panel', async () => {
    const { api, user } = setup(null)
    await user.click(screen.getAllByRole('button', { name: /^Hands of session/ })[0]!)
    expect(api.listPlayHands).toHaveBeenCalled()
    await user.click(await screen.findByRole('button', { name: 'Analyse hand 2' }))
    expect(await screen.findByRole('region', { name: 'Summary' })).toBeInTheDocument()
    // closing returns to the start panel
    await user.click(screen.getByRole('button', { name: 'Close analysis' }))
    expect(screen.getByRole('button', { name: 'Start session' })).toBeInTheDocument()
  })

  it('closing the analysis puts focus back on the button that opened it', async () => {
    const { user } = setup(null)
    await user.click(screen.getAllByRole('button', { name: /^Hands of session/ })[0]!)
    const opener = await screen.findByRole('button', { name: 'Analyse hand 2' })
    await user.click(opener)
    await screen.findByRole('region', { name: 'Summary' })
    await user.click(screen.getByRole('button', { name: 'Close analysis' }))
    expect(screen.getByRole('button', { name: 'Analyse hand 2' })).toHaveFocus()
  })

  it('an opener that never took focus (a mouse click in Safari): closing focuses the heading', async () => {
    setup(null)
    // fireEvent clicks without focusing, so the "opener" is the body
    fireEvent.click(screen.getAllByRole('button', { name: /^Hands of session/ })[0]!)
    const opener = await screen.findByRole('button', { name: 'Analyse hand 2' })
    ;(document.activeElement as HTMLElement | null)?.blur()
    expect(document.activeElement).toBe(document.body)
    fireEvent.click(opener)
    await screen.findByRole('region', { name: 'Summary' })
    ;(document.activeElement as HTMLElement | null)?.blur()
    fireEvent.click(screen.getByRole('button', { name: 'Close analysis' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Play' })).toHaveFocus())
  })

  it('after End session (the hand and its panel go away) the heading takes focus', () => {
    const session = playSessionFixture('hero_to_act')
    const props = {
      settings: settingsFixture(),
      shortcutsOn: false,
      api: {
        getPlayAnalysis: vi.fn<PlayPageApi['getPlayAnalysis']>(),
        postPlayDecision: vi.fn<PlayPageApi['postPlayDecision']>(),
        getPlayExplanation: vi.fn<PlayPageApi['getPlayExplanation']>(),
        listPlayHands: vi.fn<PlayPageApi['listPlayHands']>(async () => []),
      },
    }
    const { rerender } = render(<PlayPage flow={flowFor(session)} {...props} />)
    // the panel slot has focus while the hand runs
    expect(document.activeElement?.getAttribute('aria-label')).toBe('Action')
    rerender(<PlayPage flow={flowFor(null)} {...props} />)
    expect(screen.getByRole('heading', { name: 'Play' })).toHaveFocus()
  })
})

describe('PlayPage: the session hands and the result line', () => {
  it('Session hands is a disclosure, collapsed at first, showing the count', async () => {
    const { user } = setup(playSessionFixture('hero_to_act'))
    const toggle = screen.getByRole('button', { name: /^Session hands/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle).toHaveTextContent(String(playSessionFixture('hero_to_act').hands_played))
    expect(screen.queryByRole('table', { name: 'Hands' })).toBeNull()
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(await screen.findByRole('table', { name: 'Hands' })).toBeInTheDocument()
  })

  it('the count and the open list give nothing away before the reveal ends', async () => {
    const session = playSessionFixture('hand_over_showdown')
    const { api, user } = setup(session, { revealing: true })
    // the tally's own count: the finished hand is not counted until the reveal is over
    const toggle = screen.getByRole('button', { name: /^Session hands/ })
    expect(toggle).toHaveTextContent(`Session hands · ${session.hands_played - 1}`)
    await user.click(toggle)
    const table = await screen.findByRole('table', { name: 'Hands' })
    expect(api.listPlayHands).toHaveBeenCalledTimes(1)
    // the API already lists the finished hand with its result: the row still reads In progress
    const row = within(table).getByRole('row', { name: new RegExp(`^Hand ${session.hand!.id}\\b`) })
    expect(row).toHaveTextContent('In progress')
    expect(within(row).queryByRole('button')).toBeNull()
    expect(row).not.toHaveTextContent(/bb/)
  })

  it('the count includes the hand once the reveal is over', () => {
    const session = playSessionFixture('hand_over_showdown')
    setup(session)
    expect(screen.getByRole('button', { name: /^Session hands/ })).toHaveTextContent(
      `Session hands · ${session.hands_played}`,
    )
  })

  it('the result line is neutral: no verdict or warning attribute for a loss', () => {
    setup(playSessionFixture('hand_over_showdown'))
    const line = screen.getByText('Villain won 2.5 bb at showdown')
    expect(line.getAttribute('class') ?? '').not.toMatch(/warn|danger|mistake|blunder/i)
    expect(line).not.toHaveAttribute('data-winner')
  })
})

describe('PlayPage: the pot label of a finished hand (S10)', () => {
  const potLabel = () => screen.getByTestId('pot-label')

  it('by fold, once the reveal is over: "You take" the awarded table.pot; seats show table.stacks', () => {
    const session = playSessionFixture('hand_over_fold')
    const { table, outcome } = session.hand!
    expect(outcome?.winner).toBe('hero')
    setup(session)
    expect(potLabel()).toHaveTextContent(`You take the ${formatBb(table.pot)} pot`)
    expect(potLabel()).toHaveTextContent('You take the 3.5 bb pot')
    expect(hero()).toHaveTextContent(formatBb(table.stacks[table.hero_seat]!))
    expect(villain()).toHaveTextContent(formatBb(table.stacks[1 - table.hero_seat]!))
  })

  it('a showdown Villain wins: "Villain takes"', () => {
    const session = playSessionFixture('hand_over_showdown')
    setup(session)
    expect(potLabel()).toHaveTextContent(
      `Villain takes the ${formatBb(session.hand!.table.pot)} pot`,
    )
    expect(potLabel()).toHaveTextContent('Villain takes the 5 bb pot')
  })

  it('Villain takes a pot Hero folded; a split pot', () => {
    const base = playSessionFixture('hand_over_fold')
    const lost: PlaySessionView = {
      ...base,
      hand: {
        ...base.hand!,
        table: { ...base.hand!.table, pot: 3 },
        outcome: { ...base.hand!.outcome!, winner: 'villain', hero_delta_chips: -1 },
      },
    }
    setup(lost)
    expect(potLabel()).toHaveTextContent('Villain takes the 1.5 bb pot')
    cleanup()
    const split: PlaySessionView = {
      ...base,
      hand: {
        ...base.hand!,
        table: { ...base.hand!.table, pot: 24 },
        outcome: { ...base.hand!.outcome!, winner: 'split', hero_delta_chips: 0 },
      },
    }
    setup(split)
    expect(potLabel()).toHaveTextContent('Split pot 12 bb')
  })

  it('while the reveal runs the label is the frame\'s "Pot x bb", never the result', () => {
    const session = playSessionFixture('hand_over_showdown')
    const frames = session.hand!.frames
    // part-way through: the frame's pot
    setup(session, { shownCount: 2 })
    expect(potLabel()).toHaveTextContent(`Pot ${formatBb(frames[2]!.pot)}`)
    expect(potLabel()).not.toHaveTextContent(/takes|take|Split/)
    cleanup()
    // every entry shown but the last action's beat not over yet (revealing): still no award
    setup(session, { revealing: true })
    expect(potLabel()).toHaveTextContent(`Pot ${formatBb(session.hand!.table.pot)}`)
    expect(potLabel()).not.toHaveTextContent(/takes|take|Split/)
  })

  it('a running hand shows "Pot x bb"', () => {
    const session = playSessionFixture('hero_to_act')
    setup(session)
    expect(potLabel()).toHaveTextContent(`Pot ${formatBb(session.hand!.table.pot)}`)
  })
})

describe('PlayPage: the analysis replaces the table', () => {
  it('with the analysis open the table is gone and there is exactly one analysis', async () => {
    const { user } = setup(playSessionFixture('hand_over_showdown'))
    await user.click(screen.getByRole('button', { name: 'Analyse this hand' }))
    await screen.findByRole('region', { name: 'Summary' })
    expect(screen.queryByRole('group', { name: /^Hero,/ })).toBeNull()
    expect(screen.queryByRole('form', { name: 'Your answer' })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Hand over' })).toBeNull()
    expect(screen.getAllByRole('region', { name: 'Hand analysis' })).toHaveLength(1)
    expect(screen.getAllByRole('region', { name: 'Summary' })).toHaveLength(1)
  })

  it('closing it restores the table and the hand-over panel with Next hand', async () => {
    const { user } = setup(playSessionFixture('hand_over_showdown'))
    await user.click(screen.getByRole('button', { name: 'Analyse this hand' }))
    await user.click(await screen.findByRole('button', { name: 'Close analysis' }))
    expect(screen.getByRole('group', { name: /^Hero,/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Next hand/ })).toBeInTheDocument()
  })

  it('B4: the Action panel shows the analysed hand’s history, step by step, then the current one', async () => {
    const session = playSessionFixture('hero_to_act')
    const FULL = playHandAnalysisFixture()
    // an earlier hand whose every step opens to 5.5 bb (the current hand opens to 2.5 bb)
    const earlier = {
      ...FULL,
      decisions: FULL.decisions.map((d) => ({
        ...d!,
        view: {
          ...d!.view!,
          history: d!.view!.history.map((h, i) => (i === 0 ? { ...h, to: 11 } : h)),
        },
      })),
    }
    const { api, user } = setup(session)
    api.getPlayAnalysis.mockResolvedValue(earlier)
    const history = () => screen.getByRole('complementary')
    expect(history()).toHaveTextContent('opens to 2.5 bb')
    await user.click(screen.getByRole('button', { name: /^Session hands/ }))
    await user.click(await screen.findByRole('button', { name: 'Analyse hand 2' }))
    await screen.findByRole('region', { name: 'Summary' })
    // the worst step (the river, 7 entries) opens first
    await waitFor(() => expect(history()).toHaveTextContent('opens to 5.5 bb'))
    expect(history()).not.toHaveTextContent('opens to 2.5 bb')
    expect(within(history()).getAllByRole('listitem')).toHaveLength(
      earlier.decisions[3]!.view.history.length,
    )
    // another step: its own history
    await user.click(
      within(screen.getByRole('list', { name: 'Decisions' })).getAllByRole('button')[1]!,
    )
    await waitFor(() =>
      expect(within(history()).getAllByRole('listitem')).toHaveLength(
        earlier.decisions[1]!.view.history.length,
      ),
    )
    // closed: the current hand again
    await user.click(screen.getByRole('button', { name: 'Close analysis' }))
    expect(history()).toHaveTextContent('opens to 2.5 bb')
    expect(history()).not.toHaveTextContent('opens to 5.5 bb')
  })
})

describe('PlayPage: inside another main', () => {
  it('as="div" renders no main element', () => {
    render(
      <PlayPage
        as="div"
        flow={flowFor(playSessionFixture('hero_to_act'))}
        settings={settingsFixture()}
        shortcutsOn={false}
      />,
    )
    expect(screen.queryByRole('main')).toBeNull()
  })
})

describe('PlayPage: 5-max', () => {
  const TO_ACT = play5SessionFixture('hero_to_act')
  const FOLDED = play5SessionFixture('hero_folded')
  const SIDE = play5SessionFixture('side_pot')
  const seat = (name: string) => screen.getByRole('group', { name: new RegExp(`^${name},`) })
  const faceDown = (name: string) =>
    within(seat(name)).queryAllByRole('img', { name: 'face-down card' })

  afterEach(() => {
    try {
      window.localStorage.clear()
    } catch {
      // storage blocked
    }
  })

  it('start panel: the mode defaults to Heads-up, Start sends the choice and it is remembered', async () => {
    const onStart = vi.fn()
    const user = userEvent.setup()
    const ui = (
      <StartPanel onStart={onStart} busy={false} past={[]} onOpenHand={vi.fn()} api={undefined} />
    )
    const { unmount } = render(ui)
    const group = screen.getByRole('radiogroup', { name: 'Table' })
    expect(within(group).getByRole('radio', { name: 'Heads-up' })).toBeChecked()
    await user.click(screen.getByRole('button', { name: 'Start session' }))
    expect(onStart).toHaveBeenLastCalledWith(2)
    await user.click(within(group).getByRole('radio', { name: '5-max' }))
    expect(within(group).getByRole('radio', { name: '5-max' })).toBeChecked()
    await user.click(screen.getByRole('button', { name: 'Start session' }))
    expect(onStart).toHaveBeenLastCalledWith(5)
    unmount()
    // a later visit starts on the remembered mode
    render(ui)
    expect(screen.getByRole('radio', { name: '5-max' })).toBeChecked()
  })

  it('the mode choice works with the arrow keys and survives blocked storage', async () => {
    const user = userEvent.setup()
    const blocked = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const onStart = vi.fn()
    render(<StartPanel onStart={onStart} busy={false} past={[]} onOpenHand={vi.fn()} />)
    screen.getByRole('radio', { name: 'Heads-up' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('radio', { name: '5-max' })).toBeChecked()
    await user.click(screen.getByRole('button', { name: 'Start session' }))
    expect(onStart).toHaveBeenCalledWith(5)
    blocked.mockRestore()
    set.mockRestore()
  })

  it('a running hand: five seats, bots face down, Hero’s options at the decision', () => {
    setup(TO_ACT)
    // Bot 1 and Bot 2 are in the hand; Bot 3 and Bot 4 have folded and show no cards
    for (const name of ['Bot 1', 'Bot 2']) expect(faceDown(name)).toHaveLength(2)
    for (const name of ['Bot 3', 'Bot 4']) expect(faceDown(name)).toHaveLength(0)
    expect(within(seat('You')).getAllByRole('img', FACE_UP)).toHaveLength(2)
    const panel = screen.getByRole('form', { name: 'Your answer' })
    expect(within(panel).getAllByRole('button').length).toBeGreaterThan(2)
    expect(screen.getByText('Your turn')).toBeInTheDocument()
    // the log names the actors and words Hero's own entries in the second person
    const log = within(screen.getByRole('complementary'))
    expect(log.getAllByRole('listitem')).toHaveLength(TO_ACT.hand!.table.history.length)
    expect(log.getByText('Bot 4')).toBeInTheDocument()
    expect(log.getAllByText('You').length).toBeGreaterThan(0)
  })

  it('mid-reveal: the log is cut to the entries shown, the next actor is named, and cards stay down', () => {
    setup(SIDE, { shownCount: 2 })
    const log = within(screen.getByRole('complementary'))
    expect(log.getAllByRole('listitem')).toHaveLength(2)
    expect(log.getByText('Bot 2 to act')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Next hand/ })).toBeNull()
    expect(screen.queryByRole('list', { name: 'Pots' })).toBeNull()
    for (const name of ['Bot 1', 'Bot 2', 'Bot 3', 'Bot 4']) {
      expect(within(seat(name)).queryAllByRole('img', FACE_UP)).toHaveLength(0)
    }
  })

  it('the showdown is only turned over, with one award line per pot, once the reveal is over', () => {
    setup(SIDE)
    expect(within(seat('Bot 3')).getAllByRole('img', FACE_UP)).toHaveLength(2)
    expect(within(seat('Bot 4')).getAllByRole('img', FACE_UP)).toHaveLength(2)
    expect(faceDown('Bot 1')).toHaveLength(0) // folded: no cards
    const pots = screen.getByRole('list', { name: 'Pots' })
    expect(
      within(pots)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual(['Bot 3 takes the main pot, 253.5 bb', 'Bot 4 takes the side pot, 12 bb'])
    expect(screen.getByText('You lost 90.5 bb')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Next hand/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Analyse/ })).toBeNull()
  })

  it('no award lines before the reveal ends, even though the outcome is in the response', () => {
    setup(SIDE, { shownCount: SIDE.hand!.table.history.length - 1 })
    expect(screen.queryByRole('list', { name: 'Pots' })).toBeNull()
    expect(screen.queryByText(/takes the/)).toBeNull()
  })

  it('Hero folded: while the bots play out, Next hand is on offer and sends N', async () => {
    const { flow, user } = setup(FOLDED, { shownCount: 4 }, {}, true)
    const panel = screen.getByRole('region', { name: 'You folded' })
    expect(screen.queryByRole('form', { name: 'Your answer' })).toBeNull()
    await user.click(within(panel).getByRole('button', { name: /^Next hand/ }))
    expect(flow.nextHand).toHaveBeenCalledTimes(1)
    await user.keyboard('n')
    expect(flow.nextHand).toHaveBeenCalledTimes(2)
  })

  it('the page is not aria-busy during a play-out, so its live regions are announced', () => {
    setup(FOLDED, { shownCount: 4 })
    expect(screen.getByRole('main')).not.toHaveAttribute('aria-busy')
    cleanup()
    setup(SIDE, { shownCount: 3 })
    expect(screen.getByRole('main')).toHaveAttribute('aria-busy', 'true')
  })

  it('when the play-out ends, Next hand takes focus only from nowhere', () => {
    const play = (focusSessionHands: boolean) => {
      const flow = (shownCount: number) => (
        <PlayPage
          flow={flowFor(FOLDED, { shownCount })}
          settings={settingsFixture()}
          shortcutsOn={false}
        />
      )
      const { rerender } = render(flow(4))
      const other = screen.getByRole('button', { name: /^Session hands/ })
      if (focusSessionHands) other.focus()
      rerender(flow(FOLDED.hand!.table.history.length))
      return other
    }
    // focus left on the old Next hand button (now gone): it moves to the new one
    play(false)
    expect(screen.getByRole('button', { name: /^Next hand/ })).toHaveFocus()
    cleanup()
    // the player moved to another control: it keeps focus
    const other = play(true)
    expect(other).toHaveFocus()
  })

  it('a hand Hero is still in has no Next hand during the reveal', () => {
    setup(SIDE, { shownCount: 3 })
    expect(screen.queryByRole('region', { name: 'You folded' })).toBeNull()
    expect(screen.getByRole('form', { name: 'Your answer' })).toBeInTheDocument()
  })

  it('a fold after posting a blind reads "You folded, lost X bb" at the end', () => {
    const hand = FOLDED.hand!
    const posted = {
      ...FOLDED,
      hand: { ...hand, outcome: { ...hand.outcome!, hero_delta_chips: -2 } },
    }
    setup(posted)
    expect(screen.getByText('You folded, lost 1 bb')).toBeInTheDocument()
  })

  it('start panel: 5-max says four bots, the note says the bots, and Home and End pick a mode', async () => {
    const user = userEvent.setup()
    render(<StartPanel onStart={vi.fn()} busy={false} past={[]} onOpenHand={vi.fn()} />)
    const heads = screen.getByRole('radio', { name: 'Heads-up' })
    const five = screen.getByRole('radio', { name: '5-max' })
    heads.focus()
    await user.keyboard('{End}')
    expect(five).toBeChecked()
    expect(five).toHaveFocus()
    expect(screen.getByRole('heading', { name: 'Play against four bots' })).toBeInTheDocument()
    expect(screen.getByText(/^Pre-flop, the bots respond/)).toBeInTheDocument()
    await user.keyboard('{Home}')
    expect(heads).toBeChecked()
    expect(heads).toHaveFocus()
    expect(screen.getByRole('heading', { name: 'Play against a bot' })).toBeInTheDocument()
    expect(screen.getByText(/^Pre-flop, the bot responds/)).toBeInTheDocument()
  })

  it('a finished hand Hero folded has no Analyse either, and the result line works as heads-up', () => {
    setup(FOLDED)
    expect(screen.getByText('You folded')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Analyse/ })).toBeNull()
    expect(screen.getByRole('button', { name: /^Next hand/ })).toBeInTheDocument()
  })

  it('hides bot profiles when show_profile is off', () => {
    setup(TO_ACT, {}, { show_profile: false })
    expect(screen.queryAllByRole('button', { name: /^Profile / })).toHaveLength(0)
  })
})
