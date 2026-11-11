import { describe, expect, it } from 'vitest'
import type { PuzzleView } from '../api/types'
import { fixtureNames, puzzleFixture } from '../test/fixture'
import type { AnswerState } from './answer'
import {
  EMPTY_ANSWER,
  actionButtons,
  customBoundsBb,
  firstError,
  sizeLabel,
  sizeOptions,
  validateAnswer,
} from './answer'

const puzzleNames = fixtureNames()
  .filter((n) => n.startsWith('puzzle_'))
  .map((n) => n.replace(/^puzzle_/, ''))

function answer(patch: Partial<AnswerState>): AnswerState {
  return { ...EMPTY_ANSWER, ...patch }
}

function ok(state: AnswerState, view: PuzzleView) {
  const result = validateAnswer(state, view)
  if (!result.ok) throw new Error(`expected a valid answer, got ${JSON.stringify(result.errors)}`)
  return result.body
}

function errors(state: AnswerState, view: PuzzleView, customDisabled = false) {
  const result = validateAnswer(state, view, { customDisabled })
  if (result.ok) throw new Error(`expected errors, got ${JSON.stringify(result.body)}`)
  return result.errors
}

describe('actionButtons', () => {
  it('always returns the five kinds in order, enabled exactly for the kinds in options', () => {
    expect(puzzleNames.length).toBeGreaterThanOrEqual(9)
    for (const name of puzzleNames) {
      const view = puzzleFixture(name)
      const buttons = actionButtons(view)
      expect(buttons.map((b) => b.kind)).toEqual(['fold', 'check', 'call', 'bet', 'raise'])
      const kinds = new Set(view.options.map((o) => o.kind))
      for (const b of buttons) expect(b.enabled, `${name} ${b.kind}`).toBe(kinds.has(b.kind))
      // bet and raise are never both enabled
      expect(
        buttons.filter((b) => b.enabled && (b.kind === 'bet' || b.kind === 'raise')).length,
      ).toBeLessThanOrEqual(1)
    }
  })

  it('labels Call with the amount to call', () => {
    const labels = (name: string) => actionButtons(puzzleFixture(name)).map((b) => b.label)
    expect(labels('preflop_bb_facing_open')).toEqual([
      'Fold',
      'Check',
      'Call 1.5 bb',
      'Bet',
      'Raise',
    ])
    expect(labels('facing_all_in')[2]).toBe('Call 42 bb')
    expect(labels('preflop_facing_3bet')[2]).toBe('Call 5 bb')
    expect(labels('facing_postflop_raise')[2]).toBe('Call 3 bb')
    // no call option: no amount
    expect(labels('flop_unopened')[2]).toBe('Call')
    expect(labels('preflop_btn_first_in')[2]).toBe('Call')
  })
})

describe('sizes', () => {
  it('labels sizes by stripping the verb, pot for 100%, then the street total', () => {
    expect(sizeLabel({ index: 1, kind: 'bet', label: 'bet 33%', to: 4 })).toBe('33% · 2 bb')
    expect(sizeLabel({ index: 4, kind: 'bet', label: 'bet 100%', to: 13 })).toBe('pot · 6.5 bb')
    expect(sizeLabel({ index: 2, kind: 'raise', label: 'raise 2.5x', to: 12 })).toBe('2.5x · 6 bb')
    expect(sizeLabel({ index: 5, kind: 'bet', label: 'all-in', to: 195 })).toBe('all-in · 97.5 bb')
  })

  it('lists one size per aggressive option, in order, over every fixture', () => {
    for (const name of puzzleNames) {
      const view = puzzleFixture(name)
      const aggressive = view.options.filter((o) => o.kind === 'bet' || o.kind === 'raise')
      expect(sizeOptions(view).map((s) => s.index)).toEqual(aggressive.map((o) => o.index))
    }
    expect(sizeOptions(puzzleFixture('flop_unopened')).map((s) => s.label)).toEqual([
      '33% · 1.5 bb',
      '50% · 2.5 bb',
      '75% · 4 bb',
      'pot · 5 bb',
      'all-in · 97.5 bb',
    ])
    expect(sizeOptions(puzzleFixture('preflop_btn_first_in')).map((s) => s.label)).toEqual([
      '2.5x · 2.5 bb',
      '3x · 3 bb',
      'all-in · 100 bb',
    ])
    expect(sizeOptions(puzzleFixture('facing_all_in'))).toEqual([])
  })

  it('gives custom bounds in bb only when custom sizes are allowed', () => {
    expect(customBoundsBb(puzzleFixture('custom_allowed'))).toEqual({ min: 1, max: 97.5 })
    expect(customBoundsBb(puzzleFixture('facing_postflop_raise'))).toEqual({ min: 7.5, max: 97.5 })
    expect(customBoundsBb(puzzleFixture('preflop_btn_first_in'))).toBeNull()
    expect(customBoundsBb(puzzleFixture('facing_all_in'))).toBeNull()
  })
})

describe('validateAnswer: request bodies', () => {
  it('sends the option index for every passive option of every fixture', () => {
    for (const name of puzzleNames) {
      const view = puzzleFixture(name)
      for (const o of view.options.filter((o) => !['bet', 'raise'].includes(o.kind))) {
        expect(ok(answer({ equity: '40', action: o.kind }), view)).toEqual({
          equity_guess: 0.4,
          option: o.index,
        })
      }
    }
  })

  it('sends the size option index for every aggressive option of every fixture', () => {
    for (const name of puzzleNames) {
      const view = puzzleFixture(name)
      for (const o of view.options.filter((o) => ['bet', 'raise'].includes(o.kind))) {
        expect(ok(answer({ equity: '55', action: o.kind, size: o.index }), view)).toEqual({
          equity_guess: 0.55,
          option: o.index,
        })
      }
    }
  })

  it('sends custom_to in chips for a custom size, including one equal to a listed size', () => {
    const view = puzzleFixture('custom_allowed')
    const base = answer({ equity: '30', action: 'bet', size: 'custom' })
    expect(ok({ ...base, custom: '7.5' }, view)).toEqual({ equity_guess: 0.3, custom_to: 15 })
    expect(ok({ ...base, custom: '1' }, view)).toEqual({ equity_guess: 0.3, custom_to: 2 })
    expect(ok({ ...base, custom: '97.5' }, view)).toEqual({ equity_guess: 0.3, custom_to: 195 })
    expect(ok({ ...base, custom: ' 5 ' }, view)).toEqual({ equity_guess: 0.3, custom_to: 10 })
    expect(ok({ ...base, custom: '2,5' }, view)).toEqual({ equity_guess: 0.3, custom_to: 5 })
    expect(ok({ ...base, custom: '7.50' }, view)).toEqual({ equity_guess: 0.3, custom_to: 15 })
    const raise = puzzleFixture('facing_postflop_raise')
    expect(ok({ ...base, action: 'raise', custom: '11' }, raise)).toEqual({
      equity_guess: 0.3,
      custom_to: 22,
    })
  })

  it('never sends both option and custom_to', () => {
    const view = puzzleFixture('custom_allowed')
    const body = ok(answer({ equity: '30', action: 'bet', size: 2, custom: '9' }), view)
    expect(body).toEqual({ equity_guess: 0.3, option: 2 })
    expect(body).not.toHaveProperty('custom_to')
  })

  it('adds the range read when asked and set, never on the river', () => {
    const flop = puzzleFixture('flop_unopened')
    const read = answer({ equity: '40', action: 'check', rangeRead: '62', rangeSkipped: false })
    expect(ok(read, flop)).toEqual({ equity_guess: 0.4, option: 0, range_read_guess: 0.62 })
    expect(ok({ ...read, rangeSkipped: true }, flop)).toEqual({ equity_guess: 0.4, option: 0 })
    expect(ok({ ...read, rangeRead: '' }, flop)).toEqual({ equity_guess: 0.4, option: 0 })

    const river = puzzleFixture('river')
    expect(river.range_read_asked).toBe(false)
    expect(ok(read, river)).toEqual({ equity_guess: 0.4, option: 0 })
    expect(ok({ ...read, rangeRead: 'junk' }, river)).not.toHaveProperty('range_read_guess')
  })

  it('adds intent only with a bet or raise', () => {
    const view = puzzleFixture('flop_unopened')
    expect(ok(answer({ equity: '20', action: 'bet', size: 1, intent: 'bluff' }), view)).toEqual({
      equity_guess: 0.2,
      option: 1,
      intent: 'bluff',
    })
    expect(
      ok(answer({ equity: '20', action: 'bet', size: 3, intent: 'semi_bluff' }), view),
    ).toMatchObject({ intent: 'semi_bluff' })
    // a stale intent on a passive action is not sent
    expect(ok(answer({ equity: '20', action: 'check', intent: 'value' }), view)).toEqual({
      equity_guess: 0.2,
      option: 0,
    })
  })

  it('accepts 0 and 100 and a trailing % for equity', () => {
    const view = puzzleFixture('facing_all_in')
    expect(ok(answer({ equity: '0', action: 'fold' }), view).equity_guess).toBe(0)
    expect(ok(answer({ equity: '100', action: 'call' }), view).equity_guess).toBe(1)
    expect(ok(answer({ equity: '7%', action: 'call' }), view).equity_guess).toBe(0.07)
  })
})

describe('validateAnswer: errors', () => {
  const view = puzzleFixture('custom_allowed')

  it('needs an equity estimate', () => {
    expect(errors(answer({ action: 'check' }), view)).toHaveProperty('equity')
    for (const bad of ['101', '-1', '4.5', 'abc', '1e2']) {
      expect(errors(answer({ equity: bad, action: 'check' }), view).equity, bad).toMatch(/0.+100/)
    }
  })

  it('needs an action, and a size for a bet or raise', () => {
    expect(firstError(errors(answer({ equity: '40' }), view))).toMatch(/action/i)
    expect(firstError(errors(answer({ equity: '40', action: 'bet' }), view))).toMatch(/size/i)
  })

  it('rejects an action that is not offered', () => {
    expect(errors(answer({ equity: '40', action: 'call' }), view)).toHaveProperty('action')
    expect(errors(answer({ equity: '40', action: 'raise', size: 1 }), view)).toHaveProperty(
      'action',
    )
  })

  it('rejects a size that is not an aggressive option', () => {
    expect(errors(answer({ equity: '40', action: 'bet', size: 0 }), view)).toHaveProperty('size')
    expect(errors(answer({ equity: '40', action: 'bet', size: 9 }), view)).toHaveProperty('size')
  })

  it('validates custom sizes: number, 0.5 steps, bounds', () => {
    const base = answer({ equity: '40', action: 'bet', size: 'custom' })
    expect(errors({ ...base, custom: '' }, view)).toHaveProperty('custom')
    expect(errors({ ...base, custom: 'abc' }, view).custom).toMatch(/number/i)
    expect(errors({ ...base, custom: '1,000' }, view).custom).toMatch(/number/i)
    expect(errors({ ...base, custom: '1.000.5' }, view).custom).toMatch(/number/i)
    expect(errors({ ...base, custom: '2.3' }, view).custom).toMatch(/0\.5/)
    expect(errors({ ...base, custom: '0.5' }, view).custom).toBe('Between 1 bb and 97.5 bb')
    expect(errors({ ...base, custom: '98' }, view).custom).toBe('Between 1 bb and 97.5 bb')
  })

  it('rejects custom sizes when not allowed or disabled after a 409', () => {
    const noCustom = puzzleFixture('preflop_btn_first_in')
    const base = answer({ equity: '40', action: 'raise', size: 'custom', custom: '4' })
    expect(errors(base, noCustom)).toHaveProperty('custom')
    expect(errors({ ...base, action: 'bet' }, view, true)).toHaveProperty('custom')
  })

  it('rejects an invalid range read but not a skipped one', () => {
    const flop = puzzleFixture('flop_unopened')
    const base = answer({ equity: '40', action: 'check', rangeSkipped: false })
    expect(errors({ ...base, rangeRead: '150' }, flop).rangeRead).toMatch(/0.+100/)
    expect(validateAnswer({ ...base, rangeRead: '150', rangeSkipped: true }, flop).ok).toBe(true)
  })

  it('orders the first error: equity, then action, then size', () => {
    expect(firstError(errors(answer({}), view))).toMatch(/equity/i)
  })
})
