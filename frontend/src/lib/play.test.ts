import { describe, expect, it } from 'vitest'
import type { PlayOutcome } from '../api/types'
import { playSessionFixture } from '../test/fixture'
import { resultLine, shownTally, tableAt, tallyText, toActAt } from './play'

function outcome(over: Partial<PlayOutcome>): PlayOutcome {
  return {
    ended_by: 'fold',
    winner: 'hero',
    hero_delta_chips: 3,
    hero_delta_bb: 1.5,
    villain_cards: null,
    showdown: null,
    ...over,
  }
}

describe('resultLine', () => {
  it('a Hero win by fold', () => {
    expect(resultLine(outcome({}))).toBe('You won 1.5 bb')
  })

  it('a Villain win by fold', () => {
    expect(
      resultLine(outcome({ winner: 'villain', hero_delta_chips: -4, hero_delta_bb: -2 })),
    ).toBe('Villain won 2 bb')
  })

  it('a loss at showdown', () => {
    expect(
      resultLine(
        outcome({
          ended_by: 'showdown',
          winner: 'villain',
          hero_delta_chips: -24,
          hero_delta_bb: -12,
        }),
      ),
    ).toBe('Villain won 12 bb at showdown')
  })

  it('a win at showdown', () => {
    expect(
      resultLine(outcome({ ended_by: 'showdown', hero_delta_chips: 25, hero_delta_bb: 12.5 })),
    ).toBe('You won 12.5 bb at showdown')
  })

  it('a split', () => {
    expect(
      resultLine(outcome({ ended_by: 'showdown', winner: 'split', hero_delta_chips: 0 })),
    ).toBe('Split pot')
  })

  it('an abandoned hand', () => {
    expect(
      resultLine(outcome({ ended_by: 'abandoned', winner: 'villain', hero_delta_chips: -10 })),
    ).toBe('Hand ended: you gave up the pot')
  })
})

describe('tallyText', () => {
  it('shows a sign, bb and the hand count', () => {
    expect(tallyText({ net_chips: 25, hands_played: 14 })).toBe('+12.5 bb · 14 hands')
    expect(tallyText({ net_chips: -6, hands_played: 1 })).toBe('−3 bb · 1 hand')
    expect(tallyText({ net_chips: 0, hands_played: 0 })).toBe('0 bb · 0 hands')
  })

  it('shows half a bb loss with its sign', () => {
    expect(tallyText({ net_chips: -1, hands_played: 2 })).toBe('−0.5 bb · 2 hands')
  })
})

describe('shownTally', () => {
  const over = playSessionFixture('hand_over_showdown')

  it('is the session’s own tally when nothing is being revealed', () => {
    expect(shownTally(over, false)).toEqual({ net_chips: -5, hands_played: 1 })
  })

  it('leaves out a finished hand until its last action has been shown', () => {
    expect(shownTally(over, true)).toEqual({ net_chips: 0, hands_played: 0 })
  })

  it('a hand still running is not in the tally either way', () => {
    const running = playSessionFixture('hero_to_act')
    expect(shownTally(running, true)).toEqual({ net_chips: 0, hands_played: 0 })
    expect(shownTally(running, false)).toEqual({ net_chips: 0, hands_played: 0 })
  })
})

describe('tableAt and toActAt', () => {
  const hand = playSessionFixture('hand_over_showdown').hand!

  it('at the full count it is the response table itself', () => {
    expect(tableAt(hand, hand.table.history.length)).toBe(hand.table)
    expect(tableAt(hand, 99)).toBe(hand.table)
  })

  it('takes stacks, bets, pot and board length from the frame and cuts the history', () => {
    const t = tableAt(hand, 1)
    const frame = hand.frames[1]!
    expect(t.stacks).toEqual(frame.stacks)
    expect(t.street_bets).toEqual(frame.street_bets)
    expect(t.pot).toBe(frame.pot)
    expect(t.board).toEqual([])
    expect(t.street).toBe('preflop')
    expect(t.history).toHaveLength(1)
    // the frame after the call has the flop down
    const flop = tableAt(hand, 2)
    expect(flop.board).toEqual(hand.table.board.slice(0, 3))
    expect(flop.street).toBe('flop')
    expect(flop.history).toHaveLength(2)
  })

  it('works out what Hero owes in a frame', () => {
    const t = tableAt(hand, 0)
    // Hero (button) has posted 1 chip, the big blind 2
    expect(t.to_call).toBe(1)
    expect(t.pot_odds).toBeCloseTo(1 / 4)
  })

  it('says who acts at a frame', () => {
    expect(toActAt(hand, 1)).toBe('villain')
    expect(toActAt(hand, 0)).toBe('hero')
    expect(toActAt(hand, hand.table.history.length)).toBeNull()
  })
})
