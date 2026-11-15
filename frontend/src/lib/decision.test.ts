import { render, screen } from '@testing-library/react'
import { createElement, Fragment } from 'react'
import { describe, expect, it } from 'vitest'
import { MathsPanel } from '../components/Decision/MathsPanel'
import { OptionsTable } from '../components/Decision/OptionsTable'
import { RangePanel } from '../components/Decision/RangePanel'
import { attemptFixture, playHandAnalysisFixture, puzzleFixture } from '../test/fixture'
import { decisionFromAttempt, decisionFromReview, sizeText, sortedOptions } from './decision'
import { formatBb } from './format'
import { chosenLabel } from './result'

const flop = puzzleFixture('flop_unopened')
const bet = attemptFixture('bet')

describe('decisionFromAttempt', () => {
  it('takes the context from the puzzle view, with the board at the decision', () => {
    const d = decisionFromAttempt(flop, bet)
    expect(d.context.potChips).toBe(flop.pot)
    expect(d.context.board).toEqual(flop.board)
    expect(d.context.board).not.toEqual(bet.reveal.runout)
    expect(d.context.street).toBe('flop')
    expect(d.context.heroCards).toEqual(flop.hero_cards)
    expect(d.context.potOdds).toBe(flop.pot_odds)
    expect(d.context.heroStreetBetChips).toBe(0)
    expect(d.chosenLabel).toBe(chosenLabel(bet))
    expect(d.options).toBe(bet.options)
    expect(d.rangeSteps).toBe(bet.range_steps)
  })

  it('takes both street bets when facing a bet', () => {
    const d = decisionFromAttempt(puzzleFixture('facing_postflop_raise'), attemptFixture('fold'))
    expect(d.context.heroStreetBetChips).toBe(3)
    expect(d.context.villainStreetBetChips).toBe(9)
  })

  it('shows a custom size in bb', () => {
    const d = decisionFromAttempt(puzzleFixture('custom_allowed'), attemptFixture('custom'))
    expect(d.chosenLabel).toBe('Bet 1 bb')
  })
})

describe('sizeText', () => {
  const ctx = decisionFromAttempt(flop, bet).context
  it('gives bb and the share of the pot for a bet', () => {
    const o = bet.options.find((x) => x.label === 'bet 33%')!
    expect(sizeText(o, ctx)).toBe(`1.5 bb · ${Math.round((100 * o.put) / flop.pot)}% pot`)
    expect(sizeText(o, ctx)).toBe('1.5 bb · 30% pot')
  })

  it('gives just the amount for an all-in, with no pot share', () => {
    const o = bet.options.find((x) => x.label === 'all-in')!
    expect(sizeText(o, ctx)).toBe(`all-in ${formatBb(o.put)}`)
  })

  it('gives "to x bb" for a raise and nothing for fold, check, call', () => {
    const raiseDecision = decisionFromAttempt(
      puzzleFixture('facing_postflop_raise'),
      attemptFixture('call'),
    )
    const byKind = (k: string) => raiseDecision.options.find((o) => o.kind === k)!
    expect(sizeText(byKind('raise'), raiseDecision.context)).toBe('to 11 bb')
    expect(sizeText(byKind('fold'), raiseDecision.context)).toBe('')
    expect(sizeText(byKind('call'), raiseDecision.context)).toBe('')
    expect(
      sizeText(
        bet.options.find((o) => o.kind === 'check')!,
        ctx,
      ),
    ).toBe('')
  })
})

describe('sortedOptions', () => {
  it('sorts by EV descending and keeps ties in API order', () => {
    const base = bet.options[0]!
    const mk = (label: string, ev_bb: number) => ({ ...base, label, ev_bb })
    const sorted = sortedOptions([mk('a', 1), mk('b', 2), mk('c', 1), mk('d', 2), mk('e', -1)])
    expect(sorted.map((o) => o.label)).toEqual(['b', 'd', 'a', 'c', 'e'])
  })

  it('does not change its input', () => {
    const before = bet.options.map((o) => o.label)
    sortedOptions(bet.options)
    expect(bet.options.map((o) => o.label)).toEqual(before)
  })
})

describe('decisionFromReview', () => {
  const analysis = playHandAnalysisFixture()
  const review = analysis.decisions[1]!

  it('takes the context from the review’s table and has no intent', () => {
    const d = decisionFromReview(review)
    expect(d.context.street).toBe(review.view!.street)
    expect(d.context.potChips).toBe(review.view!.pot)
    expect(d.context.board).toEqual(review.view!.board)
    expect(d.context.heroCards).toEqual(review.view!.hero_cards)
    expect(d.grade.intent).toBeNull()
    expect(d.grade.intent_flag).toBeNull()
    expect(d.grade.verdict).toBe(review.grade!.verdict)
    expect(d.options).toBe(review.options)
    expect(d.rangeSteps).toBe(review.range_steps)
    expect(d.chosenLabel).toBe('Check')
  })

  it('renders in the options, maths and range panels', () => {
    const d = decisionFromReview(review)
    render(
      createElement(
        Fragment,
        null,
        createElement(OptionsTable, { decision: d }),
        createElement(MathsPanel, { decision: d }),
        createElement(RangePanel, { decision: d }),
      ),
    )
    expect(screen.getAllByRole('table').length).toBeGreaterThan(0)
  })

  it('shows a custom size in bb', () => {
    const custom = {
      ...review,
      chosen_label: 'bet 14',
      grade: { ...review.grade!, chosen_label: 'bet 14' },
    }
    expect(decisionFromReview(custom).chosenLabel).toBe('Bet 7 bb')
    const raise = { ...custom, chosen_label: 'raise 15' }
    expect(decisionFromReview(raise).chosenLabel).toBe('Raise to 7.5 bb')
  })

  it('takes a pre-flop decision, which has no categories', () => {
    const d = decisionFromReview(analysis.decisions[0]!)
    expect(d.categories).toBeNull()
    expect(d.chosenLabel).toBe('Raise 2.5x')
  })

  it('refuses a review that was not graded', () => {
    expect(() => decisionFromReview({ ...review, status: 'not_graded', grade: null })).toThrow()
  })
})
