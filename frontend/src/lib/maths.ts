// The step-by-step working behind each option's EV. Every number is an API number; this only
// puts them back into the solver's formulas (backend puzzle/solve.py). A plugged-in formula is
// shown only when it reproduces the API value from the raw numbers, so the maths on screen is
// the maths that was graded. Otherwise the line shows the API value on its own.
// Before the river the solver scales Hero's equity by a realisation factor r (below 1 only out of
// position; 1 on the river, all-in, in position and in results graded before M9). Every formula
// that uses equity shows r when r is not 1, so it still reproduces the API value.
import type { OptionResult } from '../api/types'
import type { DecisionData } from './decision'
import { bbLabel, formatBb, formatEvBb, formatPct } from './format'
import { optionLabel } from './result'

export interface MathsLine {
  text: string
  result?: string
}

export interface BranchRow {
  label: string
  share: string
  equity: string | null
  value: string
  formula: string | null
}

export interface OptionMaths {
  label: string
  isBest: boolean
  isChosen: boolean
  /** empty unless the option is a call or fold facing a bet */
  potOdds: MathsLine[]
  /** empty unless bet/raise */
  foldEquity: MathsLine[]
  /** the EV derivation; the last line's result is the option's ev_bb */
  ev: MathsLine[]
  branches: BranchRow[]
  /** simplification texts for this option's codes */
  notes: string[]
}

type Branch = OptionResult['branches'][number]

/** EV tolerance in bb and fraction tolerance for "the formula reproduces the API value". */
const EV_TOL = 0.01
const FRACTION_TOL = 0.001
const MINUS = '−'

const matchesEv = (chips: number, bb: number) => Math.abs(chips / 2 - bb) < EV_TOL
const matchesFraction = (x: number, api: number) => Math.abs(x - api) < FRACTION_TOL

/** an equity inside a formula: one decimal ("41.3%") */
const eq = (e: number) => formatPct(e, 1)

/** a share or frequency: one decimal, ".0" dropped ("33.6%", "100%") */
function share(x: number): string {
  return formatPct(x, 1).replace(/\.0%$/, '%')
}

const STREET_WORDS: Record<DecisionData['context']['street'], string> = {
  preflop: 'pre-flop',
  flop: 'flop',
  turn: 'turn',
  river: 'river',
}

/** a realisation factor inside a formula: two decimals ("0.80") */
const factor = (r: number) => r.toFixed(2)

/** "Realisation (out of position, pre-flop)" → "80%": the line that precedes a formula with r */
function realisationLine(r: number, d: DecisionData): MathsLine {
  // only out-of-position factors are below 1
  const where = r < 1 ? 'out of position, ' : ''
  return { text: `Realisation (${where}${STREET_WORDS[d.context.street]})`, result: share(r) }
}

/** a bb value inside a sum, with negatives bracketed: "(−1.7 bb)" */
function term(bb: number): string {
  const text = formatEvBb(bb)
  return text.startsWith(MINUS) ? `(${text})` : text
}

/** the solver's value of one branch, in chips, with its working; null when not a formula */
function branchFormula(
  b: Branch,
  o: OptionResult,
  d: DecisionData,
): { chips: number; text: string } | null {
  const P = d.context.potChips
  if (b.label === 'Villain folds') return { chips: P, text: 'pot' }
  if (b.equity === null) return null
  const e = b.equity
  if (b.label === 'Villain checks back') {
    return { chips: e * P, text: `${eq(e)} × ${formatBb(P)}` }
  }
  const bet = /^Villain bets (\d+) — Hero (calls|folds)$/.exec(b.label)
  if (bet) {
    const chips = Number(bet[1])
    return {
      chips: Math.max(e * (P + 2 * chips) - chips, 0),
      text: `max(${eq(e)} × (${formatBb(P)} + 2 × ${formatBb(chips)}) ${MINUS} ${formatBb(chips)}, 0)`,
    }
  }
  if (b.label === 'Villain calls') {
    const vcall = o.to - d.context.villainStreetBetChips
    const r = b.realisation
    const scaled = r === 1 ? eq(e) : `${factor(r)} × ${eq(e)}`
    return {
      chips: r * e * (P + o.put + vcall) - o.put,
      text: `${scaled} × (${formatBb(P)} + ${formatBb(o.put)} + ${formatBb(vcall)}) ${MINUS} ${formatBb(o.put)}`,
    }
  }
  // re-raise branches: the value only
  return null
}

function branchRow(b: Branch, o: OptionResult, d: DecisionData): BranchRow {
  const f = branchFormula(b, o, d)
  return {
    label: bbLabel(b.label),
    share: share(b.share),
    equity: b.equity === null ? null : eq(b.equity),
    value: formatEvBb(b.value_bb),
    formula: f !== null && matchesEv(f.chips, b.value_bb) ? f.text : null,
  }
}

function evLines(o: OptionResult, d: DecisionData): MathsLine[] {
  const result = formatEvBb(o.ev_bb)
  const apiOnly: MathsLine[] = [{ text: 'EV (solver value)', result }]
  const P = d.context.potChips
  const e = d.grade.equity

  if (o.kind === 'fold') {
    return o.ev_bb === 0 ? [{ text: 'EV = 0 (folding is the baseline)', result }] : apiOnly
  }
  const r = o.realisation
  // with r = 1 the lines are exactly the pre-M9 ones
  const lead = r === 1 ? [] : [realisationLine(r, d)]
  const rE = r === 1 ? 'e' : 'r × e'
  const rEq = r === 1 ? eq(e) : `${factor(r)} × ${eq(e)}`
  if (o.kind === 'call') {
    if (!matchesEv(r * e * (P + o.put) - o.put, o.ev_bb)) return apiOnly
    return [
      ...lead,
      { text: `EV = ${rE} × (pot + call) ${MINUS} call` },
      {
        text: `= ${rEq} × (${formatBb(P)} + ${formatBb(o.put)}) ${MINUS} ${formatBb(o.put)}`,
        result,
      },
    ]
  }
  if (o.kind === 'check' && o.branches.length === 0) {
    if (!matchesEv(r * e * P, o.ev_bb)) return apiOnly
    return [...lead, { text: `EV = ${rE} × pot` }, { text: `= ${rEq} × ${formatBb(P)}`, result }]
  }
  if (o.branches.length === 0) return apiOnly
  const sum = o.branches.reduce((acc, b) => acc + b.share * b.value_bb, 0)
  if (Math.abs(sum - o.ev_bb) >= EV_TOL) return apiOnly
  // a bet or raise: the factor lives on its branches (the same one wherever it is not 1)
  const branchR = o.branches.find((b) => b.realisation !== 1)?.realisation
  return [
    ...(branchR === undefined ? [] : [realisationLine(branchR, d)]),
    { text: "EV = Σ share × value, over Villain's replies" },
    {
      text: `= ${o.branches.map((b) => `${share(b.share)} × ${term(b.value_bb)}`).join(' + ')}`,
      result,
    },
  ]
}

function potOddsLines(o: OptionResult, d: DecisionData): MathsLine[] {
  const po = d.context.potOdds
  if (po === null || (o.kind !== 'call' && o.kind !== 'fold')) return []
  const P = d.context.potChips
  const call = d.options.find((x) => x.kind === 'call')
  const e = d.grade.equity
  // the call's value uses realised equity r × e, so that is what the pot odds compare
  const r = call?.realisation ?? 1
  const lines: MathsLine[] =
    call !== undefined && matchesFraction(call.put / (P + call.put), po)
      ? [
          {
            text: `Pot odds = call / (pot + call) = ${formatBb(call.put)} / (${formatBb(P)} + ${formatBb(call.put)})`,
            result: eq(po),
          },
        ]
      : [{ text: 'Pot odds', result: eq(po) }]
  lines.push({ text: 'Your equity', result: eq(e) })
  if (r === 1) {
    lines.push({
      text:
        e >= po
          ? `${eq(e)} is above ${eq(po)}, so calling beats folding`
          : `${eq(e)} is below ${eq(po)}, so folding beats calling`,
    })
    return lines
  }
  const realised = r * e
  const which = `Your realised equity (${share(r)} of ${eq(e)} = ${eq(realised)})`
  lines.push({
    text:
      realised >= po
        ? `${which} is above the ${eq(po)} pot odds, so calling beats folding`
        : `${which} is below the ${eq(po)} pot odds, so folding beats calling`,
  })
  return lines
}

function foldEquityLines(o: OptionResult, d: DecisionData): MathsLine[] {
  if (o.kind !== 'bet' && o.kind !== 'raise') return []
  const needed = o.required_fold_equity
  const folds = o.fold_freq
  if (needed === null || folds === null) return []
  const P = d.context.potChips
  const word = o.kind
  const lines: MathsLine[] = [
    matchesFraction(o.put / (P + o.put), needed)
      ? {
          text: `Fold equity needed = ${word} / (pot + ${word}) = ${formatBb(o.put)} / (${formatBb(P)} + ${formatBb(o.put)})`,
          result: eq(needed),
        }
      : { text: 'Fold equity needed', result: eq(needed) },
    { text: 'Villain actually folds', result: share(folds) },
  ]
  lines.push({
    text:
      folds >= needed
        ? `Folds alone pay for the ${word}`
        : `Folds alone don't pay for the ${word}; it needs equity when called`,
  })
  return lines
}

export function optionMaths(o: OptionResult, d: DecisionData): OptionMaths {
  const notes = o.simplifications.flatMap((code) => {
    const s = d.simplifications.find((x) => x.code === code)
    return s ? [s.text] : []
  })
  return {
    label: o.is_chosen ? d.chosenLabel : optionLabel(o.label),
    isBest: o.is_best,
    isChosen: o.is_chosen,
    potOdds: potOddsLines(o, d),
    foldEquity: foldEquityLines(o, d),
    ev: evLines(o, d),
    branches: o.branches.map((b) => branchRow(b, o, d)),
    notes,
  }
}
