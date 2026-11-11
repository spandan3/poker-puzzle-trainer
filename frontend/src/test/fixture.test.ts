import { describe, expect, it } from 'vitest'
import type { FixtureName } from './fixture'
import { attemptFixture, fixture, fixtureNames, puzzleFixture, settingsFixture } from './fixture'

describe('fixtures', () => {
  it('loads every generated file', () => {
    expect(fixtureNames()).toEqual(
      expect.arrayContaining(['attempt_bet', 'attempt_fold', 'settings', 'puzzle_river']),
    )
    for (const name of fixtureNames()) expect(fixture<object>(name)).toBeTypeOf('object')
  })

  it('throws for an unknown name', () => {
    expect(() => fixture('nope' as FixtureName)).toThrow(/no fixture named nope/)
  })

  it('keeps the history fields the UI renders from', () => {
    const view = puzzleFixture('history_3bet_and_all_in')
    expect(view.history.filter((e) => e.kind === 'raise' && e.street === 'preflop')).toHaveLength(2)
    expect(view.history.some((e) => e.all_in)).toBe(true)
    for (const e of view.history) {
      expect(e.pot_before).toBeGreaterThanOrEqual(3)
      expect(typeof e.amount).toBe('number')
    }
  })

  it('has the spots the table needs', () => {
    expect(puzzleFixture('preflop_btn_first_in').history).toEqual([])
    expect(puzzleFixture('flop_unopened').history.filter((e) => e.street === 'flop')).toEqual([])
    expect(puzzleFixture('facing_all_in').options.map((o) => o.kind)).toEqual(['fold', 'call'])
    expect(puzzleFixture('custom_allowed').custom.allowed).toBe(true)
    expect(puzzleFixture('river').range_read_asked).toBe(false)
  })

  it('has attempt results and settings', () => {
    expect(attemptFixture('bet').answer.action.kind).toBe('bet')
    expect(attemptFixture('fold').answer.action.kind).toBe('fold')
    expect(settingsFixture().profiles.length).toBeGreaterThan(0)
  })
})
