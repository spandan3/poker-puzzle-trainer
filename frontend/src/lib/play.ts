// Pure helpers for the Play page: the result line, the session tally, and the table as it stood
// at any point of the bot's reveal (looked up in the hand's `frames`).
import type {
  PlayHandView,
  PlayOutcome,
  PlayReveal,
  PlaySessionView,
  SeatView,
  StreetName,
  TableView,
} from '../api/types'
import { formatBb, formatEvBb, MINUS } from './format'

/** The line under the table when a hand is over. */
export function resultLine(outcome: PlayOutcome): string {
  if (outcome.ended_by === 'abandoned') return 'Hand ended: you gave up the pot'
  if (outcome.winner === 'split') return 'Split pot'
  const amount = formatBb(Math.abs(outcome.hero_delta_chips))
  const who = outcome.winner === 'hero' ? 'You' : 'Villain'
  return `${who} won ${amount}${outcome.ended_by === 'showdown' ? ' at showdown' : ''}`
}

/**
 * The line under a 5-max table when the hand is over, from Hero's side: "You won 31 bb at
 * showdown", "You lost 6 bb", "You folded". Who took each pot is in `awardLines`.
 */
export function resultLine5(outcome: PlayOutcome, heroFolded: boolean): string {
  if (outcome.ended_by === 'abandoned') return 'Hand ended: you gave up the pot'
  const amount = formatBb(Math.abs(outcome.hero_delta_chips))
  const atShowdown = outcome.ended_by === 'showdown' ? ' at showdown' : ''
  if (outcome.hero_delta_chips > 0) return `You won ${amount}${atShowdown}`
  if (outcome.hero_delta_chips < 0)
    return `${heroFolded ? 'You folded, lost' : 'You lost'} ${amount}`
  return heroFolded ? 'You folded' : 'You broke even'
}

/** Whether Hero has a fold in the history (the bots may still be playing the hand out). */
export function heroFolded(history: PlayHandView['table']['history']): boolean {
  return history.some((e) => e.actor === 'hero' && e.kind === 'fold')
}

/** The tail of a split line: nothing, "(plus an odd chip)" or "(plus N odd chips)". */
function oddChips(rem: number): string {
  if (rem === 0) return ''
  return rem === 1 ? ' (plus an odd chip)' : ` (plus ${rem} odd chips)`
}

/**
 * One line per pot of a finished 5-max hand, by the API's pot labels: "Bot 3 takes the side pot,
 * 12 bb", "You take the main pot, 31 bb", "Main pot split: You, Bot 1, 12 bb each". A single side
 * pot reads "side pot" (the API calls it "side pot 1").
 */
export function awardLines(outcome: PlayOutcome, seats: readonly SeatView[]): string[] {
  const sides = outcome.pots.filter((p) => p.label.startsWith('side pot')).length
  const name = (seat: number) => seats.find((s) => s.seat === seat)?.name ?? `Seat ${seat}`
  return outcome.pots.map((pot) => {
    const label = sides === 1 && pot.label === 'side pot 1' ? 'side pot' : pot.label
    const winners = pot.winners.map(name)
    if (winners.length === 1) {
      const heroWins = seats.find((s) => s.seat === pot.winners[0])?.is_hero === true
      return `${winners[0]} ${heroWins ? 'take' : 'takes'} the ${label}, ${formatBb(pot.amount)}`
    }
    const each = Math.floor(pot.amount / winners.length)
    const rem = pot.amount % winners.length
    return `${label[0]!.toUpperCase()}${label.slice(1)} split: ${winners.join(', ')}, ${formatBb(each)} each${oddChips(rem)}`
  })
}

/** A net result in chips, shown in bb with its sign: `+12.5 bb`, `MINUS 3 bb`, `0 bb`. */
export function signedBb(chips: number): string {
  const sign = chips > 0 ? '+' : chips < 0 ? MINUS : ''
  return `${sign}${formatBb(Math.abs(chips))}`
}

/**
 * The same text from an amount the API already gives in bb (e.g. a session's `net_bb`), so the
 * screen does no chips arithmetic: `signedBbFromBb(c / 2) === signedBb(c)` for whole chips `c`.
 */
export function signedBbFromBb(bb: number): string {
  const text = formatEvBb(bb)
  return Number(bb.toFixed(2)) > 0 ? `+${text}` : text
}

/** Who took a finished hand's pot, and the awarded pot (`table.pot` of the finished hand). */
export interface Award {
  winner: PlayOutcome['winner']
  potChips: number
}

/**
 * The pot label of a finished hand: "You take the 6 bb pot", "Villain takes the 1.5 bb pot",
 * "Split pot 12 bb". It names the whole pot, so it never reads as the net result beside it.
 */
export function awardText(award: Award): string {
  const pot = formatBb(award.potChips)
  if (award.winner === 'split') return `Split pot ${pot}`
  return award.winner === 'hero' ? `You take the ${pot} pot` : `Villain takes the ${pot} pot`
}

/**
 * The session's tally as the screen may show it: a finished hand counts only once the bot's last
 * action has been shown (`revealing` false), so the tally never spoils the result.
 */
export function shownTally(
  session: PlaySessionView,
  revealing: boolean,
): Pick<PlaySessionView, 'net_chips' | 'hands_played'> {
  const hand = session.hand
  if (revealing && hand?.status === 'complete' && hand.outcome) {
    return {
      net_chips: session.net_chips - hand.outcome.hero_delta_chips,
      hands_played: session.hands_played - 1,
    }
  }
  return { net_chips: session.net_chips, hands_played: session.hands_played }
}

/** `+12.5 bb · 14 hands`. */
export function tallyText(session: Pick<PlaySessionView, 'net_chips' | 'hands_played'>): string {
  const hands = session.hands_played
  return `${signedBb(session.net_chips)} · ${hands} ${hands === 1 ? 'hand' : 'hands'}`
}

const STREET_BY_BOARD_LEN: Record<number, StreetName> = {
  0: 'preflop',
  3: 'flop',
  4: 'turn',
  5: 'river',
}

/** Who acts after the first `shownCount` history entries (null: the hand is over). */
export function toActAt(hand: PlayHandView, shownCount: number): 'hero' | 'villain' | null {
  const frame = hand.frames[Math.min(shownCount, hand.frames.length - 1)]
  return frame?.to_act ?? null
}

/**
 * The table after the first `shownCount` history entries. Stacks, bets, pot and the board length
 * come from `frames[shownCount]` (to call and pot odds are left out: they are the API's numbers);
 * the history is cut to the entries shown. At or past the full count it is the response's own
 * table (for a finished hand: the settled one).
 */
export function tableAt(hand: PlayHandView, shownCount: number): TableView {
  const full = hand.table
  if (shownCount >= full.history.length) return full
  const frame = hand.frames[shownCount]
  if (!frame) return full
  return {
    ...full,
    street: STREET_BY_BOARD_LEN[frame.board_len] ?? full.street,
    board: full.board.slice(0, frame.board_len),
    history: full.history.slice(0, shownCount),
    stacks: frame.stacks,
    street_bets: frame.street_bets,
    pot: frame.pot,
    // the amount to call and the pot odds are the API's numbers (capped by Hero's stack): a
    // frame before the end is never Hero's turn to answer, so it shows none
    to_call: 0,
    pot_odds: null,
  }
}

/** The showdown of a played hand as the Hand tab says it; a hand without one says so. */
export function revealShowdownLine(reveal: PlayReveal): string {
  const { showdown } = reveal
  if (showdown === null) return 'No showdown.'
  const hands = `${showdown.hero_hand} vs ${showdown.villain_hand}`
  if (showdown.winner === 'split') return `Split pot: ${hands}`
  return `${showdown.winner === 'hero' ? 'Hero' : 'Villain'} wins: ${hands}`
}
