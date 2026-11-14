import { describe, expect, it } from 'vitest'
import type { AttemptResult, OptionResult } from '../api/types'
import { attemptFixture, puzzleFixture } from '../test/fixture'
import { neverContinuesAttempt } from '../test/synthetic'
import type { DecisionData } from './decision'
import { decisionFromAttempt } from './decision'
import { formatEvBb } from './format'
import { optionMaths } from './maths'

type Branch = OptionResult['branches'][number]

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

function decision(attempt: string, puzzle?: string): DecisionData {
  const p = puzzle ?? PAIRS.find(([a]) => a === attempt)?.[1]
  if (p === undefined) throw new Error(`no puzzle for ${attempt}`)
  return decisionFromAttempt(puzzleFixture(p), attemptFixture(attempt))
}

function neverContinues(): DecisionData {
  const result: AttemptResult = neverContinuesAttempt()
  return decisionFromAttempt(puzzleFixture('flop_unopened'), result)
}

/** The solver's value for a branch, recomputed from raw API numbers; null when not a formula. */
function recompute(b: Branch, o: OptionResult, d: DecisionData): number | null {
  const P = d.context.potChips
  if (b.label === 'Villain folds') return P
  if (b.equity === null) return null
  if (b.label === 'Villain checks back') return b.equity * P
  const bet = /^Villain bets (\d+)/.exec(b.label)
  if (bet) {
    const chips = Number(bet[1])
    return Math.max(b.equity * (P + 2 * chips) - chips, 0)
  }
  if (b.label === 'Villain calls') {
    const vcall = o.to - d.context.villainStreetBetChips
    return b.realisation * b.equity * (P + o.put + vcall) - o.put
  }
  return null
}

const ALL = [
  ...PAIRS.map(([a, p]) => ({ name: a, d: decision(a, p) })),
  { name: 'never_continues', d: neverContinues() },
]

describe('optionMaths', () => {
  for (const { name, d } of ALL) {
    it(`${name}: every option's EV ends on the API value; branch formulas reproduce`, () => {
      for (const o of d.options) {
        const m = optionMaths(o, d)
        expect(m.ev.at(-1)?.result).toBe(formatEvBb(o.ev_bb))
        m.branches.forEach((row, i) => {
          const b = o.branches[i]
          if (b === undefined) throw new Error('branch rows follow the API branches')
          if (row.formula !== null) {
            const v = recompute(b, o, d)
            expect(v).not.toBeNull()
            expect(Math.abs((v ?? NaN) / 2 - b.value_bb)).toBeLessThan(0.01)
          }
        })
        expect(JSON.stringify(m)).not.toContain('NaN')
      }
    })
  }

  it('attempt_check_river: formulas for both checks back and bets', () => {
    const d = decision('check_river')
    const check = d.options.find((o) => o.kind === 'check')
    if (!check) throw new Error('no check')
    const m = optionMaths(check, d)
    const back = m.branches.find((b) => b.label === 'Villain checks back')
    const bets = m.branches.filter((b) => b.label.startsWith('Villain bets'))
    expect(back?.formula).not.toBeNull()
    expect(bets.length).toBeGreaterThan(0)
    for (const b of bets) expect(b.formula).not.toBeNull()
    // labels in bb, "you fold"
    expect(bets[0]?.label).toBe('Villain bets 4.5 bb — you fold')
    expect(bets[0]?.formula).toContain('max(')
  })

  it('attempt_call: the call EV formula with real numbers', () => {
    const d = decision('call')
    const call = d.options.find((o) => o.kind === 'call')
    if (!call) throw new Error('no call')
    const m = optionMaths(call, d)
    const texts = m.ev.map((l) => l.text)
    expect(texts).toContain('EV = e × (pot + call) − call')
    // pot 11 bb, call 3 bb, equity 37.5%
    expect(texts).toContain('= 37.5% × (11 bb + 3 bb) − 3 bb')
    expect(m.ev.at(-1)?.result).toBe('2.25 bb')
    expect(m.potOdds[0]).toEqual({
      text: 'Pot odds = call / (pot + call) = 3 bb / (11 bb + 3 bb)',
      result: '21.4%',
    })
    expect(m.foldEquity).toEqual([])
  })

  it('a bet: fold equity needed vs actual, and branches in bb', () => {
    const d = decision('bet')
    const bet = d.options.find((o) => o.is_chosen)
    if (!bet) throw new Error('no chosen')
    const m = optionMaths(bet, d)
    expect(m.potOdds).toEqual([])
    expect(m.foldEquity[0]).toEqual({
      text: 'Fold equity needed = bet / (pot + bet) = 1.5 bb / (5 bb + 1.5 bb)',
      result: '23.1%',
    })
    expect(m.foldEquity[1]).toEqual({ text: 'Villain actually folds', result: '33.6%' })
    expect(m.branches.map((b) => b.label)).toEqual([
      'Villain folds',
      'Villain calls',
      'Villain raises to 4.5 bb — you call',
    ])
    // re-raise: value only
    expect(m.branches[2]?.formula).toBeNull()
    expect(m.isBest).toBe(true)
    expect(m.isChosen).toBe(true)
  })

  it('attempt_never_continues: one branch, Villain folds 100%, no NaN', () => {
    const d = neverContinues()
    const bet = d.options.find((o) => o.is_chosen)
    if (!bet) throw new Error('no chosen')
    const m = optionMaths(bet, d)
    expect(m.branches).toHaveLength(1)
    expect(m.branches[0]).toMatchObject({ label: 'Villain folds', share: '100%', equity: null })
    expect(m.ev.at(-1)?.result).toBe('5 bb')
    expect(JSON.stringify(m)).not.toContain('NaN')
  })

  it('attempt_fold_preflop: fold is the baseline', () => {
    const d = decision('fold_preflop')
    const fold = d.options.find((o) => o.kind === 'fold')
    if (!fold) throw new Error('no fold')
    const m = optionMaths(fold, d)
    expect(m.ev.map((l) => l.text)).toEqual(['EV = 0 (folding is the baseline)'])
    expect(m.branches).toEqual([])
    expect(m.notes).toEqual([])
  })

  it('attempt_raise_preflop: notes include the preflop_size text', () => {
    const d = decision('raise_preflop')
    const raise = d.options.find((o) => o.is_chosen)
    if (!raise) throw new Error('no chosen')
    const m = optionMaths(raise, d)
    const text = d.simplifications.find((s) => s.code === 'preflop_size')?.text
    expect(text).toBeDefined()
    expect(m.notes).toContain(text)
    expect(m.foldEquity[0]?.text).toBe(
      'Fold equity needed = raise / (pot + raise) = 5 bb / (3.5 bb + 5 bb)',
    )
  })

  it('a formula that does not reproduce the API value is replaced by the API value', () => {
    const d = decision('call')
    const call = d.options.find((o) => o.kind === 'call')
    if (!call) throw new Error('no call')
    const off = { ...call, ev_bb: call.ev_bb + 1, ev_chips: call.ev_chips + 2 }
    const m = optionMaths(off, d)
    expect(m.ev).toEqual([{ text: 'EV (solver value)', result: formatEvBb(off.ev_bb) }])
  })

  it('a pre-flop BB call out of position: the realisation factor is in the formula', () => {
    const d = decision('raise_preflop')
    const call = d.options.find((o) => o.kind === 'call')
    if (!call) throw new Error('no call')
    expect(call.realisation).toBe(0.8)
    const m = optionMaths(call, d)
    expect(m.ev).toEqual([
      { text: 'Realisation (out of position, pre-flop)', result: '80%' },
      { text: 'EV = r × e × (pot + call) − call' },
      { text: '= 0.80 × 51.2% × (3.5 bb + 1.5 bb) − 1.5 bb', result: formatEvBb(call.ev_bb) },
    ])
    // the formula reproduces the API value
    const P = d.context.potChips
    const chips = call.realisation * d.grade.equity * (P + call.put) - call.put
    expect(Math.abs(chips / 2 - call.ev_bb)).toBeLessThan(0.01)
    expect(formatEvBb(call.ev_bb)).toBe('0.55 bb')
  })

  it('pot odds compare realised equity, on the call and the fold, when r is not 1', () => {
    const d = decision('raise_preflop')
    for (const kind of ['call', 'fold'] as const) {
      const o = d.options.find((x) => x.kind === kind)
      if (!o) throw new Error(`no ${kind}`)
      const m = optionMaths(o, d)
      expect(m.potOdds).toEqual([
        {
          text: 'Pot odds = call / (pot + call) = 1.5 bb / (3.5 bb + 1.5 bb)',
          result: '30.0%',
        },
        { text: 'Your equity', result: '51.2%' },
        {
          text: 'Your realised equity (80% of 51.2% = 41.0%) is above the 30.0% pot odds, so calling beats folding',
        },
      ])
    }
  })

  it('pot odds below realised equity: folding beats calling', () => {
    const base = decision('raise_preflop')
    // equity 35%: above the 30% pot odds, but 80% of it (28%) is below them
    const d: DecisionData = { ...base, grade: { ...base.grade, equity: 0.35 } }
    const fold = d.options.find((x) => x.kind === 'fold')
    if (!fold) throw new Error('no fold')
    expect(optionMaths(fold, d).potOdds.at(-1)?.text).toBe(
      'Your realised equity (80% of 35.0% = 28.0%) is below the 30.0% pot odds, so folding beats calling',
    )
  })

  it('an out-of-position flop check: EV = r × e × pot', () => {
    const d = decision('bet')
    const check = d.options.find((o) => o.kind === 'check')
    if (!check) throw new Error('no check')
    expect(check.realisation).toBe(0.88)
    const m = optionMaths(check, d)
    expect(m.ev).toEqual([
      { text: 'Realisation (out of position, flop)', result: '88%' },
      { text: 'EV = r × e × pot' },
      { text: '= 0.88 × 46.4% × 5 bb', result: '2.04 bb' },
    ])
  })

  it("a bet's Villain-calls branch shows r × e; an all-in branch (r = 1) does not", () => {
    const d = decision('bet')
    const bet = d.options.find((o) => o.label === 'bet 33%')
    if (!bet) throw new Error('no bet 33%')
    const m = optionMaths(bet, d)
    const calls = m.branches.find((b) => b.label === 'Villain calls')
    expect(calls?.formula).toBe('0.88 × 36.4% × (5 bb + 1.5 bb + 1.5 bb) − 1.5 bb')
    expect(m.ev[0]).toEqual({ text: 'Realisation (out of position, flop)', result: '88%' })
    expect(m.ev.at(-1)?.result).toBe(formatEvBb(bet.ev_bb))
    const allIn = d.options.find((o) => o.label === 'all-in')
    if (!allIn) throw new Error('no all-in')
    const a = optionMaths(allIn, d)
    expect(a.branches.find((b) => b.label === 'Villain calls')?.formula).toBe(
      '19.4% × (5 bb + 97.5 bb + 97.5 bb) − 97.5 bb',
    )
    expect(a.ev.map((l) => l.text)).not.toContain('Realisation (out of position, flop)')
  })

  it('r = 1 (a pre-M9 result, or in position): no realisation line, formulas as before', () => {
    const d = decision('call')
    for (const o of d.options) {
      const m = optionMaths(o, d)
      const text = JSON.stringify(m)
      expect(text).not.toContain('Realisation')
      expect(text).not.toContain('realised')
      expect(text).not.toContain('r × e')
    }
    const call = d.options.find((o) => o.kind === 'call')
    if (!call) throw new Error('no call')
    expect(optionMaths(call, d).potOdds.at(-1)).toEqual({
      text: '37.5% is above 21.4%, so calling beats folding',
    })
  })

  it('r-scaled call and check values show a formula, never the solver value alone', () => {
    for (const name of ['bet', 'raise_preflop']) {
      const d = decision(name)
      for (const o of d.options) {
        if (o.kind !== 'call' && o.kind !== 'check') continue
        expect(optionMaths(o, d).ev.map((l) => l.text)).not.toContain('EV (solver value)')
      }
    }
  })

  it('the custom choice uses the display label', () => {
    const d = decision('custom')
    const chosen = d.options.find((o) => o.is_chosen)
    if (!chosen) throw new Error('no chosen')
    expect(optionMaths(chosen, d).label).toBe('Bet 1 bb')
  })
})
