import type { HeadsUpTable, TableFrame, TableView } from '../api/types'

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
  /** Out of the hand: drawn muted with a "Folded" tag, and no cards. Absent means false. */
  folded?: boolean
  /** Has no chips behind and is still in the hand ("All-in" tag). Absent: derived from the stack. */
  allIn?: boolean
  /** Deal-in delay per card (on a new puzzle); no animation when omitted. */
  dealDelaysMs?: number[]
  /** The cards were just revealed: they flip face up. */
  flip?: boolean
}

export interface SeatsOptions {
  showProfile: boolean
  /** Villain's hole cards, known only after a submit. Until then they stay face down. */
  villainCards?: string[]
}

const BUTTON_POSITION = 'BTN'

/** The seats of a heads-up table: Hero at the bottom, Villain at the top. */
export function seatsFromView(view: HeadsUpTable, opts: SeatsOptions): SeatInfo[] {
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
      position: view.villain_position ?? '',
      stackChips: view.stacks[villainSeat] ?? 0,
      betChips: view.street_bets[villainSeat] ?? 0,
      isHero: false,
      isButton: view.villain_position === BUTTON_POSITION,
      cards: revealed ? [...opts.villainCards!] : [null, null],
      faceDown: !revealed,
      profile: view.villain_profile
        ? { label: view.villain_profile.label, description: view.villain_profile.description }
        : undefined,
      showProfile: opts.showProfile,
    },
  ]
}

export interface PlaySeatsOptions {
  showProfile: boolean
  /**
   * One frame of the hand's replay (`hand.frames[i]`): its stacks, street bets and folded flags
   * replace the view's, so the table can be drawn at any point of the reveal.
   */
  frame?: Pick<TableFrame, 'stacks' | 'street_bets' | 'folded'>
  /**
   * Show the cards the view carries for the bots (a showdown). The view holds the hand's final
   * cards, so a table drawn at an earlier frame must not show them: this defaults to false when a
   * `frame` is given, and to true otherwise (the view's own table). Pass true for the reveal step
   * or once the hand is over. A shown bot's cards flip face up (`flip`).
   */
  revealed?: boolean
}

/** Slots of the other seats, clockwise from Hero (who sits at the bottom). */
const OTHER_SLOTS: Record<number, readonly SeatSlot[]> = {
  2: ['top'],
  5: ['bottom-left', 'top-left', 'top-right', 'bottom-right'],
}

/**
 * The seats of a played table (2 or 5 seats) from the API's per-seat views, Hero first. The other
 * seats follow clockwise from Hero (increasing seat index). Cards: Hero's own, and the cards of a
 * seat the API shows (a showdown) when `revealed`; any other seat is face down. A folded seat shows no cards.
 */
export function seatsFromPlayTable(view: TableView, opts: PlaySeatsOptions): SeatInfo[] {
  const n = view.seats.length
  const slots = OTHER_SLOTS[n]
  if (!slots) throw new Error(`no seat layout for ${n} seats`)
  const hero = view.hero_seat
  const revealed = opts.revealed ?? opts.frame === undefined
  const order = Array.from({ length: n }, (_, i) => (hero + i) % n)
  return order.map((index, i): SeatInfo => {
    const seat = view.seats.find((s) => s.seat === index)
    if (!seat) throw new Error(`no view for seat ${index}`)
    const { frame } = opts
    const stack = frame?.stacks[index] ?? seat.stack
    const folded = frame?.folded[index] ?? seat.folded
    const known = seat.is_hero ? seat.cards !== null : revealed && seat.cards !== null
    return {
      slot: i === 0 ? 'bottom' : slots[i - 1]!,
      name: seat.name,
      position: seat.position,
      stackChips: stack,
      betChips: frame?.street_bets[index] ?? seat.street_bet,
      isHero: seat.is_hero,
      isButton: seat.is_button,
      cards: folded ? [] : known ? [...seat.cards!] : [null, null],
      faceDown: !folded && !known,
      flip: known && !seat.is_hero && opts.revealed === true ? true : undefined,
      profile: seat.profile
        ? { label: seat.profile.label, description: seat.profile.description }
        : undefined,
      showProfile: !seat.is_hero && opts.showProfile,
      folded,
      allIn: frame ? stack === 0 && !folded : seat.all_in,
    }
  })
}
