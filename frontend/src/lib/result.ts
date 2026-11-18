// Pure helpers for the result strip: option labels, the verdict line, guesses vs truth.
import type { ActionLogEntry, AttemptResult, PuzzleView } from '../api/types'
import { formatBb, formatEvBb, formatPct } from './format'
import { pts } from './stats'

type Grade = AttemptResult['grade']
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

/** A custom size's server label: the kind and the chips, with no % or x ("bet 14", "raise 15"). */
const CUSTOM_LABEL = /^(bet|raise) (\d+)$/

/** The chosen label of a played decision: a custom size (in chips on the server) shown in bb. */
export function reviewChosenLabel(serverLabel: string): string {
  const custom = CUSTOM_LABEL.exec(serverLabel)
  if (custom === null) return optionLabel(serverLabel)
  const to = formatBb(Number(custom[2]))
  return custom[1] === 'raise' ? `Raise to ${to}` : `Bet ${to}`
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
  return gradeLine(chosenLabel(result), result.grade)
}

/** The same line from the chosen label (already for display) and the grade's numbers. */
export function gradeLine(
  chosen: string,
  grade: Pick<Grade, 'verdict' | 'ev_loss_bb' | 'best_label'>,
): string {
  const you = `You: ${chosen}`
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
  /** the API's error (`equity_error`, `range_read_error`) in points, as Progress shows it */
  error: string | null
  score: Score | null
  /** the score badge's title */
  scoreTitle: string
}

/**
 * Equity guess vs truth, and the range read when it was asked. Each number is an API field,
 * rounded on its own: at a .x5 boundary the shown difference of guess and actual can differ from
 * the shown error by 0.1 (all three are the API's numbers).
 */
export function guessLines(result: AttemptResult): GuessLine[] {
  const { grade } = result
  const lines: GuessLine[] = [
    {
      label: 'Equity',
      guess: formatPct(grade.equity_guess),
      actual: formatPct(grade.equity, 1),
      error: pts(grade.equity_error),
      score: grade.equity_score,
      scoreTitle: 'How close your equity estimate was',
    },
  ]
  if (grade.range_read_guess !== null && grade.ahead_now !== null) {
    lines.push({
      label: 'Range read',
      guess: formatPct(grade.range_read_guess),
      actual: formatPct(grade.ahead_now, 1),
      error: grade.range_read_error === null ? null : pts(grade.range_read_error),
      score: grade.range_read_score,
      scoreTitle: 'How close your range read was',
    })
  }
  return lines
}

/** "Your estimate 45% · actual 46.4% · off by 1.4 pts" */
export function guessText(line: GuessLine): string {
  const off = line.error === null ? '' : ` · off by ${line.error}`
  return `Your estimate ${line.guess} · actual ${line.actual}${off}`
}

/** Hero folded (on any street): there is no run-out and no showdown. */
export function heroFolded(result: AttemptResult): boolean {
  return result.answer.action.kind === 'fold'
}

/** The one note on how a hand was judged: after a fold the sampled run-out doesn't apply. */
export const FOLD_NOTE = "Graded against Villain's whole range."

/** The API's judged-on-range note, or the fold wording when Hero folded (no run-out was dealt). */
export function judgedNote(apiNote: string, heroFoldedHand: boolean): string {
  return heroFoldedHand ? FOLD_NOTE : apiNote
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
