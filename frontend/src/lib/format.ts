/** Chips are half big blinds: the API speaks chips, the UI speaks bb. */

/**
 * The minus sign every negative number on screen uses (U+2212), never a hyphen. This file is the
 * only one that spells it: everything else imports `MINUS` (a test checks).
 */
export const MINUS = '\u2212'

export function chipsToBb(chips: number): number {
  return chips / 2
}

/** Nearest chip count for an amount in big blinds. */
export function bbToChips(bb: number): number {
  return Math.round(bb * 2)
}

/**
 * `5` -> "2.5 bb", `200` -> "100 bb". Chips are integers, so bb is a multiple of 0.5.
 *
 * For amounts, which are never negative: pot, stacks, bets, calls, sizes and bounds. A negative
 * would print an ASCII "-" (as `bb` in backend explain/format.py does), not `MINUS`, so a signed result goes
 * through `signedBb` (lib/play.ts) or `formatEvBb`, which take the sign themselves.
 */
export function formatBb(chips: number): string {
  const whole = Math.trunc(chips / 2)
  const half = Math.abs(chips % 2) === 1
  return `${half && chips < 0 && whole === 0 ? '-' : ''}${whole}${half ? '.5' : ''} bb`
}

/**
 * Display only: swaps the space before "bb" for a no-break space, so an amount never splits from
 * its unit across two lines. `formatBb` itself stays plain, so tests and API comparisons match.
 */
export function nowrapUnits(text: string): string {
  return text.replace(/ (?=bb\b)/g, '\u00a0')
}

/** A fraction as a percentage: `0.256` -> "26%" (or "25.6%" with one digit). */
export function formatPct(x: number, digits = 0): string {
  return `${(x * 100).toFixed(digits)}%`
}

const FALLBACK_DETAIL = 'Something went wrong'

/** The text for an API error `detail`: a string as is, a validation array as its messages. */
export function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item: unknown) => {
      if (typeof item === 'object' && item !== null && 'msg' in item) {
        const { msg } = item as { msg: unknown }
        if (typeof msg === 'string') return [msg]
      }
      return []
    })
    if (messages.length > 0) return messages.join('; ')
  }
  return FALLBACK_DETAIL
}

/** An EV in bb from the API's `*_bb` floats: two decimals, no trailing zeros ("2.25 bb"), `MINUS` for negatives. */
export function formatEvBb(bb: number): string {
  const n = Number(bb.toFixed(2))
  return `${n < 0 ? MINUS : ''}${Math.abs(n)} bb`
}

/** An EV in bb with two fixed decimals, so a column lines up: `0.7` -> "0.70 bb". */
export function bb2(x: number): string {
  const n = Number(x.toFixed(2))
  return `${n < 0 ? MINUS : ''}${Math.abs(n).toFixed(2)} bb`
}

/**
 * A server label with chips in it, shown in bb: "Villain raises to 40 — Hero folds" becomes
 * "Villain raises to 20 bb — you fold". Labels without chips pass through.
 */
export function bbLabel(label: string): string {
  return label
    .replace(/\b(to|bets?) (\d+)(?![\d%])/g, (_m, word: string, chips: string) => {
      return `${word} ${formatBb(Number(chips))}`
    })
    .replace(/\bHero (fold|call)s\b/g, 'you $1')
}
