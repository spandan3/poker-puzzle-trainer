// Formatting and scales for the Progress page. The numbers come from the API; this only shows them.
import { formatEvBb, formatPct } from './format'

/** An equity or range-read error (a fraction) in percentage points: `0.042` -> "4.2 pts". */
export function pts(x: number): string {
  return `${(x * 100).toFixed(1)} pts`
}

/** A share as a whole percentage: `0.88` -> "88%". */
export function pct(x: number): string {
  return formatPct(x)
}

/** EV lost in bb with one decimal: `1.577` -> "1.6 bb". */
export function bb1(x: number): string {
  return `${x.toFixed(1)} bb`
}

/**
 * How the last 50 compare with the 50 before. EV lost is a cost, so lower is better. `null`
 * when either side is missing.
 */
export function deltaText(last: number | null, prev: number | null): string | null {
  if (last === null || prev === null) return null
  const diff = Number(Math.abs(prev - last).toFixed(2))
  if (diff === 0) return 'same as the 50 before'
  return `${formatEvBb(diff)} ${last < prev ? 'better' : 'worse'} than the 50 before`
}

/** The browser's IANA time zone, or "UTC" when it can't be read. */
export function localTimeZone(): string {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone
    return typeof zone === 'string' && zone !== '' ? zone : 'UTC'
  } catch {
    return 'UTC'
  }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-11-12" -> "Nov 12" (no Date, so no time zone can shift the day). */
export function shortDate(iso: string): string {
  const [, month, day] = iso.split('-')
  const name = MONTHS[Number(month) - 1]
  return name === undefined || day === undefined ? iso : `${name} ${Number(day)}`
}

export interface Scale {
  /** the top of the axis (a multiple of `step`) */
  max: number
  step: number
  /** 0, step, 2·step … max */
  ticks: number[]
}

/** A y scale from 0 up to a round maximum above `max`, with about `count` gridlines. */
export function chartScale(max: number, count = 4): Scale {
  if (!(max > 0) || !Number.isFinite(max))
    return { max: 1, step: 0.25, ticks: [0, 0.25, 0.5, 0.75, 1] }
  const raw = max / count
  const pow = 10 ** Math.floor(Math.log10(raw))
  const unit = raw / pow
  const nice = unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10
  const step = nice * pow
  const top = Math.ceil(max / step - 1e-9) * step
  const ticks: number[] = []
  for (let i = 0; i * step <= top + step / 1e6; i++) ticks.push(Number((i * step).toPrecision(12)))
  return { max: ticks[ticks.length - 1]!, step, ticks }
}
