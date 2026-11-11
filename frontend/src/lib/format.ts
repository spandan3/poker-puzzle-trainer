/** Chips are half big blinds: the API speaks chips, the UI speaks bb. */

export function chipsToBb(chips: number): number {
  return chips / 2
}

/** Nearest chip count for an amount in big blinds. */
export function bbToChips(bb: number): number {
  return Math.round(bb * 2)
}

/** `5` -> "2.5 bb", `200` -> "100 bb". Chips are integers, so bb is a multiple of 0.5. */
export function formatBb(chips: number): string {
  const whole = Math.trunc(chips / 2)
  const half = Math.abs(chips % 2) === 1
  return `${half && chips < 0 && whole === 0 ? '-' : ''}${whole}${half ? '.5' : ''} bb`
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
