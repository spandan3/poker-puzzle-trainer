import type { ActionLogEntry, HeadsUpTable, StreetName, TableFrame, TableView } from '../api/types'
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

/** Who acted (or acts next) at a 5-max table: the seat's display name and position. */
export interface ActorLabel {
  name: string
  position: string
  isHero: boolean
}

/**
 * The action log of a table with more than two seats: who took each history entry, and who acts
 * after the last one shown (null: nobody, the hand is over).
 */
export interface SeatLog {
  entries: ActorLabel[]
  next: ActorLabel | null
}

/**
 * One entry as a verb phrase for a named actor, in bb: "raises to 7.5 bb", or for Hero ("You")
 * "raise to 7.5 bb". Pre-flop raises are not numbered here (limps and several callers occur).
 */
export function seatActionText(e: ActionLogEntry, hero: boolean): string {
  const verb = (base: string) => (hero ? base : `${base}s`)
  switch (e.kind) {
    case 'fold':
      return verb('fold')
    case 'check':
      return verb('check')
    case 'call':
      return `${verb('call')} ${formatBb(e.amount)}${e.all_in ? ' (all-in)' : ''}`
    case 'bet':
      if (e.all_in) return `${hero ? 'go' : 'goes'} all-in to ${formatBb(e.to)}`
      return `${verb('bet')} ${formatBb(e.to)} (${Math.round((100 * e.to) / e.pot_before)}% pot)`
    case 'raise':
      if (e.all_in) return `${hero ? 'go' : 'goes'} all-in to ${formatBb(e.to)}`
      return `${verb('raise')} to ${formatBb(e.to)}`
  }
}

/** "Bot 2 raises to 7.5 bb", "You call 2 bb". */
export function actionLine(actor: Pick<ActorLabel, 'name'>, text: string): string {
  return `${actor.name} ${text}`
}

/**
 * The log of a played 5-max hand cut to the first `shownCount` entries. The actor of entry k is
 * `frames[k].to_act_seat` (the history itself only says hero or villain), named from the view's
 * seats; `next` is the actor at `frames[shownCount]`.
 */
export function seatLogAt(
  view: Pick<TableView, 'seats' | 'hero_seat'>,
  frames: readonly Pick<TableFrame, 'to_act_seat'>[],
  history: readonly ActionLogEntry[],
  shownCount: number,
): SeatLog {
  const label = (seatIndex: number | null | undefined): ActorLabel | null => {
    if (seatIndex === null || seatIndex === undefined) return null
    const seat = view.seats.find((s) => s.seat === seatIndex)
    return seat ? { name: seat.name, position: seat.position, isHero: seat.is_hero } : null
  }
  const entries = history.slice(0, shownCount).map((e, k): ActorLabel => {
    const found = label(frames[k]?.to_act_seat ?? (e.actor === 'hero' ? view.hero_seat : null))
    return (
      found ?? {
        name: e.actor === 'hero' ? 'You' : 'Bot',
        position: '',
        isHero: e.actor === 'hero',
      }
    )
  })
  const upcoming = frames[Math.min(shownCount, frames.length - 1)]
  return { entries, next: label(upcoming?.to_act_seat) }
}

export interface HistoryItem {
  actor: 'hero' | 'villain'
  /** The actor's table position (BTN, BB). */
  position: string
  text: string
  /** The actor's display name at a table with several bots (otherwise Hero / Villain). */
  name?: string
}

export interface HistorySection {
  street: StreetName
  /** The board cards that arrived on this street (none pre-flop). */
  board: string[]
  entries: HistoryItem[]
  toAct?: 'hero' | 'villain'
  /** Who `toAct` is, by name, at a table with several bots. */
  toActName?: string
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
 * `toAct` says who the last section is waiting for (default Hero); `null` for a finished hand.
 */
export function groupHistory(
  view: HeadsUpTable,
  answer?: ActionLogEntry,
  toAct: 'hero' | 'villain' | null = 'hero',
  seatLog?: SeatLog,
): HistorySection[] {
  const texts = seatLog
    ? view.history.map((e, j) => seatActionText(e, seatLog.entries[j]?.isHero ?? false))
    : entryTexts(answer ? [...view.history, answer] : view.history)
  const streets = STREET_ORDER.slice(0, STREET_ORDER.indexOf(view.street) + 1)
  return streets.map((street, i) => {
    const [from, to] = BOARD_SLICE[street]
    const entries: HistoryItem[] = []
    view.history.forEach((e, j) => {
      if (e.street !== street) return
      const who = seatLog?.entries[j]
      entries.push({
        actor: e.actor,
        position: who
          ? who.position
          : ((e.actor === 'hero' ? view.hero_position : view.villain_position) ?? ''),
        text: texts[j]!,
        ...(who ? { name: who.name } : {}),
      })
    })
    const section: HistorySection = { street, board: view.board.slice(from, to), entries }
    if (i === streets.length - 1) {
      if (answer) {
        section.answer = { actor: 'hero', position: view.hero_position, text: texts.at(-1)! }
      } else {
        if (toAct !== null) section.toAct = toAct
        if (toAct !== null && seatLog?.next) section.toActName = seatLog.next.name
      }
    }
    return section
  })
}
