import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { PlaySessionView, SettingsView } from '../../api/types'
import type { PlayFlow, PlayState } from '../../app/usePlayFlow'
import { playSessionFixture, playSessionsFixture, settingsFixture } from '../../test/fixture'
import { PlayPage } from './PlayPage'

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
  const onAnalyse = vi.fn()
  render(
    <PlayPage
      flow={flow}
      settings={{ ...settingsFixture(), ...settings }}
      shortcutsOn={shortcutsOn}
      onAnalyse={onAnalyse}
    />,
  )
  return { flow, onAnalyse, user: userEvent.setup() }
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

  it('Analyse this hand calls onAnalyse with the hand id', async () => {
    const session = playSessionFixture('hand_over_showdown')
    const { onAnalyse, user } = setup(session)
    await user.click(screen.getByRole('button', { name: 'Analyse this hand' }))
    expect(onAnalyse).toHaveBeenCalledWith(session.hand!.id)
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
    const list = screen.getByRole('list', { name: 'Past sessions' })
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[1]).toHaveTextContent('−52.5 bb')
    expect(items[1]).toHaveTextContent('13 hands')
    await user.click(screen.getByRole('button', { name: 'Start session' }))
    expect(flow.start).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('group', { name: /^Hero,/ })).toBeNull()
  })

  it('no past sessions: no list', () => {
    setup(null, { past: [] })
    expect(screen.queryByRole('list', { name: 'Past sessions' })).toBeNull()
  })

  it('Start session is disabled while starting', () => {
    setup(null, { busy: true })
    expect(screen.getByRole('button', { name: 'Start session' })).toBeDisabled()
  })
})
