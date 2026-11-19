// The pot-odds tie cases shared with the backend: backend/tests/explain/test_tie_cases.py reads
// the same file through the Why text's facts, so the Maths tab and the Why text agree on when
// equity and pot odds tie and which way the decision goes.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { AttemptResult, PuzzleView } from '../api/types'
import { attemptFixture, puzzleFixture } from '../test/fixture'
import type { DecisionData } from './decision'
import { decisionFromAttempt } from './decision'
import { comparePotOdds, optionMaths } from './maths'

interface TieCase {
  name: string
  equity: number
  pot_odds: number
  realisation: number
  expected_tie: boolean
  expected_beats: boolean
  /** r × e (or e when r is 1) and the pot odds as both sides show them */
  expected_shown_equity: string
  expected_shown_pot_odds: string
}

const { cases } = JSON.parse(
  readFileSync(resolve(import.meta.dirname, '../../../backend/tests/data/tie_cases.json'), 'utf8'),
) as { cases: TieCase[] }

/** attempt_call's decision with the case's equity, pot odds and call realisation */
function decisionFor(c: TieCase): DecisionData {
  const base = decisionFromAttempt(puzzleFixture('facing_postflop_raise'), attemptFixture('call'))
  return {
    ...base,
    context: { ...base.context, potOdds: c.pot_odds },
    grade: { ...base.grade, equity: c.equity },
    options: base.options.map((o) =>
      o.kind === 'call' ? { ...o, realisation: c.realisation } : o,
    ),
  }
}

describe('shared tie cases (backend/tests/data/tie_cases.json)', () => {
  it('has the cases', () => {
    expect(cases.length).toBeGreaterThanOrEqual(8)
    // pot odds off a shown value: a tie rule on the gap (|r × e − po| < 0.0005) fails these
    expect(cases.some((c) => c.pot_odds === 1 / 3 && c.expected_tie)).toBe(true)
    expect(cases.some((c) => c.pot_odds === 1 / 3 && !c.expected_tie)).toBe(true)
  })

  for (const c of cases) {
    it(c.name, () => {
      const cmp = comparePotOdds(c.equity, c.pot_odds, c.realisation)
      expect(cmp.shownEquity).toBe(c.expected_shown_equity)
      expect(cmp.shownPotOdds).toBe(c.expected_shown_pot_odds)
      expect(cmp.tie).toBe(c.expected_tie)
      expect(cmp.beats).toBe(c.expected_beats)

      // and the line the Maths tab shows says the same
      const d = decisionFor(c)
      const fold = d.options.find((o) => o.kind === 'fold')
      if (!fold) throw new Error('no fold')
      const text = optionMaths(fold, d).potOdds.at(-1)?.text ?? ''
      expect(text).toContain(c.expected_shown_equity)
      expect(text).toContain(c.expected_shown_pot_odds)
      expect(text).toContain(
        c.expected_beats ? 'so calling beats folding' : 'so folding beats calling',
      )
      expect(text.includes('realised')).toBe(c.realisation !== 1)
      if (c.expected_tie) {
        expect(text).toContain(c.expected_beats ? ' is exactly the ' : ' falls just short of the ')
        expect(text).not.toMatch(/ is (above|below) /)
      } else {
        expect(text).toContain(c.expected_beats ? ' is above ' : ' is below ')
      }
    })
  }
})

// every attempt fixture with the puzzle it was made on
const PAIRS: [string, string][] = [
  ['bet', 'flop_unopened'],
  ['fold', 'facing_postflop_raise'],
  ['call', 'facing_postflop_raise'],
  ['raise_preflop', 'preflop_bb_facing_open'],
  ['fold_preflop', 'preflop_btn_first_in'],
  ['check_river', 'river'],
  ['custom', 'custom_allowed'],
]

describe('the Maths tab compares what the facts compare', () => {
  for (const [a, p] of PAIRS) {
    it(`attempt_${a}: the shown pot odds are the graded ones; a factor only with a call option`, () => {
      const view = puzzleFixture(p) as PuzzleView
      const result = attemptFixture(a) as AttemptResult
      // the Maths tab reads view.pot_odds, the facts read grade.pot_odds
      expect(view.pot_odds).toBe(result.grade.pot_odds)
      const d = decisionFromAttempt(view, result)
      const call = d.options.find((o) => o.kind === 'call')
      for (const o of d.options) {
        const lines = optionMaths(o, d).potOdds
        if (lines.length === 0) continue
        // facts.py: r is the call option's realisation, and only when a call option exists
        const r = call?.realisation ?? 1
        expect(lines.at(-1)?.text.includes('realised')).toBe(r !== 1)
      }
    })
  }

  it('with no call option there is no realisation factor', () => {
    const base = decisionFromAttempt(
      puzzleFixture('preflop_bb_facing_open'),
      attemptFixture('raise_preflop'),
    )
    expect(base.options.find((o) => o.kind === 'call')?.realisation).toBe(0.8)
    const d: DecisionData = { ...base, options: base.options.filter((o) => o.kind !== 'call') }
    const fold = d.options.find((o) => o.kind === 'fold')
    if (!fold) throw new Error('no fold')
    const text = optionMaths(fold, d).potOdds.at(-1)?.text ?? ''
    expect(text).not.toContain('realised')
    expect(text).toBe('51.2% is above 30.0%, so calling beats folding')
  })
})
