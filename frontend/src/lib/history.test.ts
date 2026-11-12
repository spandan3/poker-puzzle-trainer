import { describe, expect, it } from 'vitest'
import type { ActionLogEntry, PuzzleView, StreetName } from '../api/types'
import { fixtureNames, puzzleFixture } from '../test/fixture'
import { entryTexts, groupHistory } from './history'

function entry(over: Partial<ActionLogEntry>): ActionLogEntry {
  return {
    actor: 'hero',
    all_in: false,
    amount: 0,
    kind: 'check',
    pot_before: 3,
    street: 'preflop',
    text: 'server text',
    to: 0,
    ...over,
  }
}

const raise = (to: number, over: Partial<ActionLogEntry> = {}) =>
  entry({ kind: 'raise', to, amount: to, ...over })

describe('entryTexts', () => {
  it('names pre-flop raises opens / 3-bets / 4-bets', () => {
    const texts = entryTexts([
      raise(5),
      raise(15, { actor: 'villain', pot_before: 7 }),
      raise(34, { pot_before: 20 }),
    ])
    expect(texts).toEqual(['opens to 2.5 bb', '3-bets to 7.5 bb', '4-bets to 17 bb'])
  })

  it('counts only pre-flop raises, not calls or post-flop raises', () => {
    const texts = entryTexts([
      raise(5),
      entry({ kind: 'call', actor: 'villain', amount: 3, to: 5, pot_before: 7 }),
      entry({ kind: 'bet', street: 'flop', to: 6, amount: 6, pot_before: 10 }),
      raise(20, { street: 'flop', actor: 'villain', pot_before: 16 }),
    ])
    expect(texts).toEqual([
      'opens to 2.5 bb',
      'calls 1.5 bb',
      'bets 3 bb (60% pot)',
      'raises to 10 bb',
    ])
  })

  it('renders post-flop bets with a rounded percentage of the pot', () => {
    expect(
      entryTexts([entry({ kind: 'bet', street: 'turn', to: 38, amount: 38, pot_before: 50 })]),
    ).toEqual(['bets 19 bb (76% pot)'])
    expect(
      entryTexts([entry({ kind: 'bet', street: 'flop', to: 10, amount: 10, pot_before: 30 })]),
    ).toEqual(['bets 5 bb (33% pot)'])
    expect(
      entryTexts([entry({ kind: 'bet', street: 'river', to: 5, amount: 5, pot_before: 8 })]),
    ).toEqual(['bets 2.5 bb (63% pot)'])
  })

  it('renders an all-in bet or raise as all-in to, pre-flop and post-flop', () => {
    expect(
      entryTexts([
        entry({ kind: 'bet', street: 'river', to: 90, amount: 90, pot_before: 60, all_in: true }),
        raise(175, { street: 'turn', all_in: true, amount: 175 }),
        raise(200, { all_in: true, amount: 200 }),
      ]),
    ).toEqual(['all-in to 45 bb', 'all-in to 87.5 bb', 'all-in to 100 bb'])
  })

  it('renders calls with the amount and an all-in call', () => {
    expect(
      entryTexts([
        entry({ kind: 'call', amount: 10, to: 15 }),
        entry({ kind: 'call', amount: 111, to: 175, all_in: true }),
      ]),
    ).toEqual(['calls 5 bb', 'calls 55.5 bb (all-in)'])
  })

  it('renders checks and folds', () => {
    expect(entryTexts([entry({ kind: 'check' }), entry({ kind: 'fold' })])).toEqual([
      'checks',
      'folds',
    ])
  })

  it('returns an empty list for no history', () => {
    expect(entryTexts([])).toEqual([])
  })

  it.each(fixtureNames().filter((n) => n.startsWith('puzzle_')))(
    'renders every entry of %s',
    (name) => {
      const view = puzzleFixture(name.replace('puzzle_', ''))
      const texts = entryTexts(view.history)
      expect(texts).toHaveLength(view.history.length)
      for (const t of texts)
        expect(t).toMatch(/^(opens|3-bets|4-bets|bets|raises|all-in|calls|checks|folds)/)
      view.history.forEach((e, i) => {
        if (e.kind === 'call') expect(texts[i]).toContain('bb')
        if (e.all_in && (e.kind === 'bet' || e.kind === 'raise')) {
          expect(texts[i]).toMatch(/^all-in to /)
        }
      })
    },
  )

  it('matches the known text of the 3-bet and all-in fixture', () => {
    expect(entryTexts(puzzleFixture('history_3bet_and_all_in').history)).toEqual([
      'opens to 2.5 bb',
      '3-bets to 7.5 bb',
      'calls 5 bb',
      'bets 5 bb (33% pot)',
      'calls 5 bb',
      'checks',
      'bets 19 bb (76% pot)',
      'all-in to 87.5 bb',
    ])
  })
})

describe('groupHistory', () => {
  const STREETS: StreetName[] = ['preflop', 'flop', 'turn', 'river']

  it('has one section per street up to the decision street with its board cards', () => {
    const view = puzzleFixture('history_3bet_and_all_in')
    const groups = groupHistory(view)
    expect(groups.map((g) => g.street)).toEqual(['preflop', 'flop', 'turn'])
    expect(groups.map((g) => g.board)).toEqual([[], ['9d', 'Jd', '2c'], ['7d']])
    expect(groups.map((g) => g.entries.length)).toEqual([3, 2, 3])
    expect(groups[0]!.entries[0]).toMatchObject({ actor: 'hero', text: 'opens to 2.5 bb' })
    expect(groups[2]!.entries[2]).toMatchObject({ actor: 'villain', text: 'all-in to 87.5 bb' })
  })

  it('includes an empty decision street and marks only the last section Hero to act', () => {
    const view = puzzleFixture('flop_unopened')
    const groups = groupHistory(view)
    expect(groups.map((g) => g.street)).toEqual(['preflop', 'flop'])
    expect(groups[1]).toMatchObject({ board: ['3h', '2s', '6s'], entries: [], toAct: 'hero' })
    expect(groups[0]!.toAct).toBeUndefined()
  })

  it('gives the pre-flop decision a single section with no board', () => {
    const groups = groupHistory(puzzleFixture('preflop_btn_first_in'))
    expect(groups).toHaveLength(1)
    expect(groups[0]).toMatchObject({ street: 'preflop', board: [], toAct: 'hero' })
  })

  it('carries each entry actor position', () => {
    const view = puzzleFixture('flop_unopened')
    const first = groupHistory(view)[0]!.entries[0]!
    expect(first.position).toBe(view.villain_position)
  })

  it.each(fixtureNames().filter((n) => n.startsWith('puzzle_')))('is consistent for %s', (name) => {
    const view: PuzzleView = puzzleFixture(name.replace('puzzle_', ''))
    const groups = groupHistory(view)
    expect(groups.map((g) => g.street)).toEqual(STREETS.slice(0, STREETS.indexOf(view.street) + 1))
    expect(groups.flatMap((g) => g.board)).toEqual(view.board)
    expect(groups.reduce((n, g) => n + g.entries.length, 0)).toBe(view.history.length)
    expect(groups.filter((g) => g.toAct)).toHaveLength(1)
    expect(groups.at(-1)!.toAct).toBe('hero')
  })

  it('shows a submitted answer in place of Hero to act', () => {
    const view = puzzleFixture('flop_unopened')
    const answer = {
      actor: 'hero' as const,
      street: 'flop' as const,
      kind: 'check' as const,
      to: 0,
      pot_before: view.pot,
      amount: 0,
      all_in: false,
      text: 'check',
    }
    const sections = groupHistory(view, answer)
    const last = sections.at(-1)!
    expect(last.toAct).toBeUndefined()
    expect(last.answer).toEqual({ actor: 'hero', position: view.hero_position, text: 'checks' })
    expect(sections.flatMap((s) => s.entries)).toHaveLength(view.history.length)
  })
})
