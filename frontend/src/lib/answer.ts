// Pure logic for the answer panel: which actions are offered, how sizes are labelled, and the
// request body for an answer. The UI never builds an `Action`: it sends an option index from
// `view.options`, or `custom_to` in chips when the puzzle allows custom sizes.
import type { AttemptIn, Intent, OptionBrief, PuzzleView } from '../api/types'
import { bbToChips, formatBb } from './format'

export type ActionKind = OptionBrief['kind']

export const ACTION_KINDS: readonly ActionKind[] = ['fold', 'check', 'call', 'bet', 'raise']

export function isAggressive(kind: ActionKind | null): kind is 'bet' | 'raise' {
  return kind === 'bet' || kind === 'raise'
}

export interface ActionButton {
  kind: ActionKind
  enabled: boolean
  label: string
}

const ACTION_LABELS: Record<ActionKind, string> = {
  fold: 'Fold',
  check: 'Check',
  call: 'Call',
  bet: 'Bet',
  raise: 'Raise',
}

/** Always five buttons, in a fixed order; a kind absent from `options` is disabled. */
export function actionButtons(view: PuzzleView): ActionButton[] {
  const offered = new Set(view.options.map((o) => o.kind))
  return ACTION_KINDS.map((kind) => {
    const enabled = offered.has(kind)
    const label =
      kind === 'call' && enabled ? `Call ${formatBb(view.to_call)}` : ACTION_LABELS[kind]
    return { kind, enabled, label }
  })
}

/** `bet 33%` -> `33% · 2 bb`, `bet 100%` -> `pot · 6.5 bb`, `all-in` -> `all-in · 97.5 bb`. */
export function sizeLabel(option: OptionBrief): string {
  let name = option.label.replace(/^(bet|raise) /, '')
  if (name === '100%') name = 'pot'
  return `${name} · ${formatBb(option.to)}`
}

export interface SizeOption {
  index: number
  label: string
}

/** One size per bet or raise option, in the API's order. */
export function sizeOptions(view: PuzzleView): SizeOption[] {
  return view.options
    .filter((o) => isAggressive(o.kind))
    .map((o) => ({ index: o.index, label: sizeLabel(o) }))
}

/** Custom size bounds in big blinds, or null when custom sizes are not allowed. */
export function customBoundsBb(view: PuzzleView): { min: number; max: number } | null {
  const { allowed, min_to, max_to } = view.custom
  if (!allowed || min_to === null || max_to === null) return null
  return { min: min_to / 2, max: max_to / 2 }
}

/** The panel's draft answer, as typed. */
export interface AnswerState {
  /** equity estimate, percent, as typed */
  equity: string
  /** range read, percent, as typed */
  rangeRead: string
  rangeSkipped: boolean
  action: ActionKind | null
  /** an option index from `view.options`, `'custom'`, or none yet */
  size: number | 'custom' | null
  /** custom size in bb ("to"), as typed */
  custom: string
  intent: Intent | null
}

export const EMPTY_ANSWER: AnswerState = {
  equity: '',
  rangeRead: '',
  rangeSkipped: true,
  action: null,
  size: null,
  custom: '',
  intent: null,
}

export type AnswerField = 'equity' | 'rangeRead' | 'action' | 'size' | 'custom'
export type AnswerErrors = Partial<Record<AnswerField, string>>

export type Validation = { ok: true; body: AttemptIn } | { ok: false; errors: AnswerErrors }

const FIELD_ORDER: AnswerField[] = ['equity', 'rangeRead', 'action', 'size', 'custom']

export const PERCENT_ERROR = 'Enter a whole number from 0 to 100'

/** A whole percent 0..100 (an optional trailing `%`), null when empty, or an error. */
export function parsePercent(text: string): number | null | { error: string } {
  const t = text.trim()
  if (t === '') return null
  const m = /^(\d{1,3})\s*%?$/.exec(t)
  const n = m ? Number(m[1]) : NaN
  if (!(n >= 0 && n <= 100)) return { error: PERCENT_ERROR }
  return n
}

/** A custom "to" amount in bb: a number, in steps of 0.5, inside the bounds. */
export function parseCustomBb(
  text: string,
  bounds: { min: number; max: number },
): number | null | { error: string } {
  const t = text.trim()
  if (t === '') return null
  // a dot or comma decimal with at most two places: "2,5" and "7.50" are fine, while "1,000"
  // (a thousands separator) is not read as 1
  if (!/^\d+([.,]\d{1,2})?$/.test(t)) return { error: 'Enter a number in bb' }
  const bb = Number(t.replace(',', '.'))
  if (Math.abs(bb * 2 - Math.round(bb * 2)) > 1e-9) return { error: 'Use steps of 0.5 bb' }
  if (bb < bounds.min || bb > bounds.max) {
    return {
      error: `Between ${formatBb(bbToChips(bounds.min))} and ${formatBb(bbToChips(bounds.max))}`,
    }
  }
  return bb
}

/** The first error in display order (equity, range read, action, size, custom). */
export function firstError(errors: AnswerErrors): string | undefined {
  for (const field of FIELD_ORDER) if (errors[field]) return errors[field]
  return undefined
}

/**
 * Checks a draft answer against the puzzle and builds the request body: exactly one of
 * `option` / `custom_to`; `range_read_guess` only when asked and set; `intent` only with a bet
 * or raise.
 */
export function validateAnswer(
  state: AnswerState,
  view: PuzzleView,
  opts: { customDisabled?: boolean } = {},
): Validation {
  const errors: AnswerErrors = {}

  const equity = parsePercent(state.equity)
  if (equity === null) errors.equity = 'Set your equity estimate'
  else if (typeof equity === 'object') errors.equity = equity.error

  let rangeRead: number | null = null
  if (view.range_read_asked && !state.rangeSkipped) {
    const parsed = parsePercent(state.rangeRead)
    if (typeof parsed === 'object' && parsed !== null) errors.rangeRead = parsed.error
    else rangeRead = parsed
  }

  let choice: { option: number } | { custom_to: number } | null = null
  const kind = state.action
  if (kind === null) {
    errors.action = 'Choose an action'
  } else if (!view.options.some((o) => o.kind === kind)) {
    errors.action = `${ACTION_LABELS[kind]} is not an option here`
  } else if (!isAggressive(kind)) {
    const option = view.options.find((o) => o.kind === kind)
    if (option) choice = { option: option.index }
  } else if (state.size === null) {
    errors.size = 'Choose a size'
  } else if (state.size === 'custom') {
    const bounds = customBoundsBb(view)
    if (bounds === null || opts.customDisabled) {
      errors.custom = 'Custom sizes are not available'
    } else {
      const bb = parseCustomBb(state.custom, bounds)
      if (bb === null) errors.custom = 'Enter a custom size'
      else if (typeof bb === 'object') errors.custom = bb.error
      else choice = { custom_to: bbToChips(bb) }
    }
  } else {
    const index = state.size
    const option = view.options.find((o) => o.index === index && o.kind === kind)
    if (option) choice = { option: option.index }
    else errors.size = 'Choose a size'
  }

  if (Object.keys(errors).length > 0 || typeof equity !== 'number' || choice === null) {
    return { ok: false, errors }
  }

  const body: AttemptIn = { equity_guess: equity / 100, ...choice }
  if (rangeRead !== null) body.range_read_guess = rangeRead / 100
  if (isAggressive(kind) && state.intent !== null) body.intent = state.intent
  return { ok: true, body }
}
