// Pure helpers for the result strip: option labels, the verdict line, guesses vs truth.
import type { ActionLogEntry, AttemptResult, PuzzleView } from '../api/types'
import { formatBb, formatEvBb, formatPct } from './format'

export type Verdict = AttemptResult['grade']['verdict']
export type Score = AttemptResult['grade']['equity_score']

export const VERDICT_LABELS: Record<Verdict, string> = {
  best: 'Best',
  fine: 'Fine',
  mistake: 'Mistake',
  blunder: 'Blunder',
}

export const SCORE_LABELS: Record<Score, string> = {
  great: 'great',
  good: 'good',
  off: 'off',
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** An option label for display: "bet 33%" → "Bet 33%", "bet 100%" → "Bet pot", "all-in" → "All-in". */
export function optionLabel(label: string): string {
  return capitalise(label.replace(/\b100%/, 'pot'))
}

/**
 * The label of the answer the user chose. A custom size has a server label in chips
 * ("bet 14"), so it is rebuilt in bb from the stored action.
 */
export function chosenLabel(result: AttemptResult): string {
  const { answer } = result
  if (answer.custom_to !== null) {
    const to = formatBb(answer.action.to)
    return answer.action.kind === 'raise' ? `Raise to ${to}` : `Bet ${to}`
  }
  return optionLabel(answer.chosen_label)
}

/** EV differences below this (in bb) are shown as "0 bb" noise-free. */
const EV_EPSILON = 0.005

/**
 * The line under the verdict. It never repeats the verdict word:
 * - the top play: "You: Bet 33% · the top play"
 * - close to it (best / fine with some EV lost): "You: Bet 33% · within 0.11 bb of the top play (Bet 75%)"
 * - otherwise: "You: Fold · Top EV: Call · 2.25 bb lost"
 */
export function verdictLine(result: AttemptResult): string {
  const { grade } = result
  const you = `You: ${chosenLabel(result)}`
  const best = optionLabel(grade.best_label)
  const loss = grade.ev_loss_bb
  if (loss < EV_EPSILON) return `${you} · the top play`
  if (grade.verdict === 'best' || grade.verdict === 'fine') {
    return `${you} · within ${formatEvBb(loss)} of the top play (${best})`
  }
  return `${you} · Top EV: ${best} · ${formatEvBb(loss)} lost`
}

export interface GuessLine {
  label: string
  guess: string
  actual: string
  score: Score | null
}

/** Equity guess vs truth, and the range read when it was asked. */
export function guessLines(result: AttemptResult): GuessLine[] {
  const { grade } = result
  const lines: GuessLine[] = [
    {
      label: 'Equity',
      guess: formatPct(grade.equity_guess),
      actual: formatPct(grade.equity, 1),
      score: grade.equity_score,
    },
  ]
  if (grade.range_read_guess !== null && grade.ahead_now !== null) {
    lines.push({
      label: 'Range read',
      guess: formatPct(grade.range_read_guess),
      actual: formatPct(grade.ahead_now, 1),
      score: grade.range_read_score,
    })
  }
  return lines
}

/** Hero folded (on any street): there is no run-out and no showdown. */
export function heroFolded(result: AttemptResult): boolean {
  return result.answer.action.kind === 'fold'
}

/** The showdown of the sampled run-out, e.g. "Hero wins: Pair vs Pair"; none after a fold. */
export function showdownLine(result: AttemptResult): string {
  if (heroFolded(result)) return "You folded, so there's no showdown."
  const { showdown } = result.reveal
  const hands = `${showdown.hero_hand} vs ${showdown.villain_hand}`
  if (showdown.winner === 'split') return `Split pot: ${hands}`
  return `${showdown.winner === 'hero' ? 'Hero' : 'Villain'} wins: ${hands}`
}

/**
 * Hero's submitted action as a history entry, so the history can show the answer in place of
 * "Hero to act" (rendered by the same `entryTexts` rules as every other entry).
 */
export function answerEntry(view: PuzzleView, result: AttemptResult): ActionLogEntry {
  const { action } = result.answer
  const heroBet = view.street_bets[view.hero_seat] ?? 0
  const heroStack = view.stacks[view.hero_seat] ?? 0
  const amount = action.kind === 'fold' || action.kind === 'check' ? 0 : action.to - heroBet
  return {
    actor: 'hero',
    street: action.street,
    kind: action.kind,
    to: action.to,
    pot_before: view.pot,
    amount,
    all_in: amount > 0 && amount >= heroStack,
    text: result.answer.chosen_label,
  }
}
