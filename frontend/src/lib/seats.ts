import type { PuzzleView } from '../api/types'

/** Where a seat sits around the table. Heads-up uses `bottom` (Hero) and `top` (Villain). */
export const SEAT_SLOTS = [
  'bottom',
  'bottom-left',
  'top-left',
  'top',
  'top-right',
  'bottom-right',
] as const

export type SeatSlot = (typeof SEAT_SLOTS)[number]

export interface SeatProfile {
  label: string
  description: string
}

export interface SeatInfo {
  slot: SeatSlot
  name: string
  position: string
  stackChips: number
  /** Chips put in on the current street (shown as a chip stack in front of the seat). */
  betChips: number
  isHero: boolean
  isButton: boolean
  /** A `null` card is one whose identity is not known to the UI (drawn face down). */
  cards: (string | null)[]
  faceDown: boolean
  profile?: SeatProfile
  showProfile: boolean
}

export interface SeatsOptions {
  showProfile: boolean
  /** Villain's hole cards, known only after a submit. Until then they stay face down. */
  villainCards?: string[]
}

const BUTTON_POSITION = 'BTN'

/** The seats of a heads-up puzzle: Hero at the bottom, Villain at the top. */
export function seatsFromView(view: PuzzleView, opts: SeatsOptions): SeatInfo[] {
  const heroSeat = view.hero_seat
  const villainSeat = 1 - heroSeat
  const revealed = opts.villainCards !== undefined
  return [
    {
      slot: 'bottom',
      name: 'Hero',
      position: view.hero_position,
      stackChips: view.stacks[heroSeat] ?? 0,
      betChips: view.street_bets[heroSeat] ?? 0,
      isHero: true,
      isButton: view.hero_position === BUTTON_POSITION,
      cards: [...view.hero_cards],
      faceDown: false,
      showProfile: false,
    },
    {
      slot: 'top',
      name: 'Villain',
      position: view.villain_position,
      stackChips: view.stacks[villainSeat] ?? 0,
      betChips: view.street_bets[villainSeat] ?? 0,
      isHero: false,
      isButton: view.villain_position === BUTTON_POSITION,
      cards: revealed ? [...opts.villainCards!] : [null, null],
      faceDown: !revealed,
      profile: {
        label: view.villain_profile.label,
        description: view.villain_profile.description,
      },
      showProfile: opts.showProfile,
    },
  ]
}
