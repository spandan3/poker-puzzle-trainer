export type Rank = '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | 'T' | 'J' | 'Q' | 'K' | 'A'
export type Suit = 'h' | 'd' | 'c' | 's'

export interface ParsedCard {
  rank: Rank
  suit: Suit
}

const RANK_NAMES: Record<Rank, string> = {
  '2': 'Two',
  '3': 'Three',
  '4': 'Four',
  '5': 'Five',
  '6': 'Six',
  '7': 'Seven',
  '8': 'Eight',
  '9': 'Nine',
  T: 'Ten',
  J: 'Jack',
  Q: 'Queen',
  K: 'King',
  A: 'Ace',
}

const SUIT_NAMES: Record<Suit, string> = {
  h: 'hearts',
  d: 'diamonds',
  c: 'clubs',
  s: 'spades',
}

const SUIT_GLYPHS: Record<Suit, string> = { h: '♥', d: '♦', c: '♣', s: '♠' }

function isRank(x: string): x is Rank {
  return Object.hasOwn(RANK_NAMES, x)
}

function isSuit(x: string): x is Suit {
  return Object.hasOwn(SUIT_NAMES, x)
}

/** `"Th"` -> `{ rank: "T", suit: "h" }`. Throws on anything that is not a card. */
export function parseCard(card: string): ParsedCard {
  const rank = card.charAt(0)
  const suit = card.charAt(1)
  if (card.length !== 2 || !isRank(rank) || !isSuit(suit)) {
    throw new Error(`not a card: ${JSON.stringify(card)}`)
  }
  return { rank, suit }
}

/** `"Th"` -> "Ten of hearts". */
export function cardName(card: string): string {
  const { rank, suit } = parseCard(card)
  return `${RANK_NAMES[rank]} of ${SUIT_NAMES[suit]}`
}

/** The rank as printed on a card: T shows as 10. */
export function rankGlyph(rank: Rank): string {
  return rank === 'T' ? '10' : rank
}

export function suitGlyph(suit: Suit): string {
  return SUIT_GLYPHS[suit]
}
