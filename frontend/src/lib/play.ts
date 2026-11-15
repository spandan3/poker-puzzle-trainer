// Pure helpers for the Play page: the result line, the session tally, and the table as it stood
// at any point of the bot's reveal (looked up in the hand's `frames`).
import type {
  PlayHandView,
  PlayOutcome,
  PlayReveal,
  PlaySessionView,
  StreetName,
  TableView,
} from '../api/types'
import { formatBb } from './format'

/** The line under the table when a hand is over. */
export function resultLine(outcome: PlayOutcome): string {
  if (outcome.ended_by === 'abandoned') return 'Hand ended: you gave up the pot'
  if (outcome.winner === 'split') return 'Split pot'
  const amount = formatBb(Math.abs(outcome.hero_delta_chips))
  const who = outcome.winner === 'hero' ? 'You' : 'Villain'
  return `${who} won ${amount}${outcome.ended_by === 'showdown' ? ' at showdown' : ''}`
}

/** A net result in bb with its sign: `+12.5 bb`, `−3 bb` (U+2212, like the rest of the app), `0 bb`. */
export function signedBb(chips: number): string {
  const sign = chips > 0 ? '+' : chips < 0 ? '−' : ''
  return `${sign}${formatBb(Math.abs(chips))}`
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
