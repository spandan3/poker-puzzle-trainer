// The decision a result is about, as plain data, so the details components don't need the
// puzzle-specific parts of the API response (M10 will feed them a decision from a live hand).
import type { AttemptResult, OptionResult, PuzzleView, StreetName } from '../api/types'
import { chosenLabel } from './result'
import { formatBb } from './format'

type R = AttemptResult

export interface DecisionContext {
  street: StreetName
  /** total pot at the decision, including bets in front (PuzzleView.pot) */
  potChips: number
  /** street_bets[hero_seat] */
  heroStreetBetChips: number
  villainStreetBetChips: number
  potOdds: number | null
  heroCards: string[]
  /** the board at the decision, not the run-out */
  board: string[]
}

export interface DecisionData {
  context: DecisionContext
  grade: Pick<
    R['grade'],
    | 'verdict'
    | 'ev_loss_bb'
    | 'chosen_label'
    | 'best_label'
    | 'equity'
    | 'equity_std_error'
    | 'equity_exact'
    | 'ahead_now'
    | 'intent'
    | 'intent_truth'
    | 'intent_flag'
    | 'bluff_check'
  >
  /** display label, custom sizes in bb */
  chosenLabel: string
  options: R['options']
  simplifications: R['simplifications']
  categories: R['categories']
  rangeSteps: R['range_steps']
}

export function decisionFromAttempt(view: PuzzleView, result: AttemptResult): DecisionData {
  const { grade } = result
  const villainSeat = 1 - view.hero_seat
  return {
    context: {
      street: view.street,
      potChips: view.pot,
      heroStreetBetChips: view.street_bets[view.hero_seat] ?? 0,
      villainStreetBetChips: view.street_bets[villainSeat] ?? 0,
      potOdds: view.pot_odds,
      heroCards: view.hero_cards,
      board: view.board,
    },
    grade: {
      verdict: grade.verdict,
      ev_loss_bb: grade.ev_loss_bb,
      chosen_label: grade.chosen_label,
      best_label: grade.best_label,
      equity: grade.equity,
      equity_std_error: grade.equity_std_error,
      equity_exact: grade.equity_exact,
      ahead_now: grade.ahead_now,
      intent: grade.intent,
      intent_truth: grade.intent_truth,
      intent_flag: grade.intent_flag,
      bluff_check: grade.bluff_check,
    },
    chosenLabel: chosenLabel(result),
    options: result.options,
    simplifications: result.simplifications,
    categories: result.categories,
    rangeSteps: result.range_steps,
  }
}

/** "1.5 bb · 30% pot" for a bet, "to 7.5 bb" for a raise, "" for fold, check and call. */
export function sizeText(option: OptionResult, ctx: DecisionContext): string {
  if (option.kind === 'bet') {
    const share = ctx.potChips > 0 ? Math.round((100 * option.put) / ctx.potChips) : null
    return share === null ? formatBb(option.put) : `${formatBb(option.put)} · ${share}% pot`
  }
  if (option.kind === 'raise') return `to ${formatBb(option.to)}`
  return ''
}

/** Highest EV first; equal EVs keep the API's order. */
export function sortedOptions(options: readonly OptionResult[]): OptionResult[] {
  return options
    .map((option, index) => ({ option, index }))
    .sort((a, b) => b.option.ev_bb - a.option.ev_bb || a.index - b.index)
    .map(({ option }) => option)
}
