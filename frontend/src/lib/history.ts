import type { ActionLogEntry, PuzzleView, StreetName } from '../api/types'
import { formatBb } from './format'

export const STREET_ORDER: readonly StreetName[] = ['preflop', 'flop', 'turn', 'river']

export const STREET_LABELS: Record<StreetName, string> = {
  preflop: 'Pre-flop',
  flop: 'Flop',
  turn: 'Turn',
  river: 'River',
}

const PREFLOP_RAISE_NAMES = ['opens to', '3-bets to', '4-bets to']

/**
 * The action text of every history entry, in bb. Pre-flop raises are named by their number
 * (opens, 3-bets, 4-bets: blinds are not entries and limps do not occur), so a raise's text
 * depends on the entries before it.
 */
export function entryTexts(history: readonly ActionLogEntry[]): string[] {
  let preflopRaises = 0
  return history.map((e) => {
    switch (e.kind) {
      case 'fold':
        return 'folds'
      case 'check':
        return 'checks'
      case 'call':
        return e.all_in ? `calls ${formatBb(e.amount)} (all-in)` : `calls ${formatBb(e.amount)}`
      case 'bet':
      case 'raise': {
        const preflopRaise = e.kind === 'raise' && e.street === 'preflop'
        const n = preflopRaise ? preflopRaises++ : 0
        if (e.all_in) return `all-in to ${formatBb(e.to)}`
        if (e.kind === 'bet') {
          // Math.round (half up) is intentional: the server's own text is not shown.
          return `bets ${formatBb(e.to)} (${Math.round((100 * e.to) / e.pot_before)}% pot)`
        }
        if (preflopRaise) {
          return `${PREFLOP_RAISE_NAMES[n] ?? `${n + 2}-bets to`} ${formatBb(e.to)}`
        }
        return `raises to ${formatBb(e.to)}`
      }
    }
  })
}

export interface HistoryItem {
  actor: 'hero' | 'villain'
  /** The actor's table position (BTN, BB). */
  position: string
  text: string
}

export interface HistorySection {
  street: StreetName
  /** The board cards that arrived on this street (none pre-flop). */
  board: string[]
  entries: HistoryItem[]
  toAct?: 'hero'
  /** Hero's submitted answer (after a submit), in place of "Hero to act". */
  answer?: HistoryItem
}

const BOARD_SLICE: Record<StreetName, [number, number]> = {
  preflop: [0, 0],
  flop: [0, 3],
  turn: [3, 4],
  river: [4, 5],
}

/**
 * One section per street from pre-flop to the decision street (even when it has no entries).
 * With `answer` (Hero's submitted action), the last section shows it instead of "Hero to act".
 */
export function groupHistory(view: PuzzleView, answer?: ActionLogEntry): HistorySection[] {
  const texts = entryTexts(answer ? [...view.history, answer] : view.history)
  const streets = STREET_ORDER.slice(0, STREET_ORDER.indexOf(view.street) + 1)
  return streets.map((street, i) => {
    const [from, to] = BOARD_SLICE[street]
    const entries: HistoryItem[] = []
    view.history.forEach((e, j) => {
      if (e.street !== street) return
      entries.push({
        actor: e.actor,
        position: e.actor === 'hero' ? view.hero_position : view.villain_position,
        text: texts[j]!,
      })
    })
    const section: HistorySection = { street, board: view.board.slice(from, to), entries }
    if (i === streets.length - 1) {
      if (answer) {
        section.answer = { actor: 'hero', position: view.hero_position, text: texts.at(-1)! }
      } else {
        section.toAct = 'hero'
      }
    }
    return section
  })
}
