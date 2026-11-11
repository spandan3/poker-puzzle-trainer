import type { Suit } from '../../lib/cards'

// Suit shapes drawn in a 100×100 box (our own paths, so a suit never renders as an emoji).
const HEART =
  'M50 92 C47 88 4 60 4 30 C4 13 16 4 29 4 C39 4 46 10 50 19 C54 10 61 4 71 4 C84 4 96 13 96 30 C96 60 53 88 50 92 Z'
const DIAMOND = 'M50 2 C60 20 74 37 90 50 C74 63 60 80 50 98 C40 80 26 63 10 50 C26 37 40 20 50 2 Z'
const SPADE =
  'M50 2 C58 16 96 38 96 62 C96 77 85 86 72 86 C63 86 57 82 53 76 C54 86 58 93 67 98 L33 98 C42 93 46 86 47 76 C43 82 37 86 28 86 C15 86 4 77 4 62 C4 38 42 16 50 2 Z'
const CLUB_STEM = 'M46 56 C46 78 42 90 32 98 L68 98 C58 90 54 78 54 56 Z'

/** A suit shape filling a 100×100 viewBox, drawn in `currentColor`. */
export function SuitShape({ suit }: { suit: Suit }) {
  switch (suit) {
    case 'h':
      return <path d={HEART} />
    case 'd':
      return <path d={DIAMOND} />
    case 's':
      return <path d={SPADE} />
    case 'c':
      return (
        <g>
          <circle cx="50" cy="27" r="22" />
          <circle cx="26" cy="60" r="22" />
          <circle cx="74" cy="60" r="22" />
          <circle cx="50" cy="52" r="12" />
          <path d={CLUB_STEM} />
        </g>
      )
  }
}
