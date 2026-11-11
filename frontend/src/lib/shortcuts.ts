// Single-key shortcuts. `keyToCommand` is pure; `useShortcuts` binds it to `window`.
// `SHORTCUTS` is the one table used for the <kbd> hints, `aria-keyshortcuts` and the overlay.
import { useEffect, useLayoutEffect, useRef } from 'react'

export type ShortcutId =
  | 'fold'
  | 'check'
  | 'call'
  | 'aggressive'
  | 'size'
  | 'customSize'
  | 'value'
  | 'bluff'
  | 'semiBluff'
  | 'focusEquity'
  | 'focusRangeRead'
  | 'submit'
  | 'escape'
  | 'next'
  | 'help'

/** `n` is the 1-based size number for `size`. */
export interface Command {
  id: ShortcutId
  n?: number
}

export type ShortcutGroup = 'Answer' | 'Action' | 'Size' | 'Intent' | 'Puzzle'

export interface Shortcut {
  id: ShortcutId
  /** the keys as shown in <kbd> hints */
  keys: string[]
  /** shown in the overlay instead of every key, e.g. "1–9" */
  keysLabel?: string
  /** the `aria-keyshortcuts` value (space-separated alternatives) */
  aria: string
  description: string
  group: ShortcutGroup
  /** `panel`: shown on the answer panel's controls; `app`: on the app's own controls */
  scope: 'panel' | 'app'
}

const DIGITS = ['1', '2', '3', '4', '5', '6', '7', '8', '9']

export const SHORTCUTS: readonly Shortcut[] = [
  {
    id: 'focusEquity',
    keys: ['E'],
    aria: 'E',
    description: 'Equity estimate',
    group: 'Answer',
    scope: 'panel',
  },
  {
    id: 'focusRangeRead',
    keys: ['A'],
    aria: 'A',
    description: 'Range read (% of the range you are ahead of)',
    group: 'Answer',
    scope: 'panel',
  },
  {
    id: 'submit',
    keys: ['Enter'],
    aria: 'Enter',
    description: 'Submit the answer',
    group: 'Answer',
    scope: 'panel',
  },
  { id: 'fold', keys: ['F'], aria: 'F', description: 'Fold', group: 'Action', scope: 'panel' },
  { id: 'check', keys: ['X'], aria: 'X', description: 'Check', group: 'Action', scope: 'panel' },
  { id: 'call', keys: ['C'], aria: 'C', description: 'Call', group: 'Action', scope: 'panel' },
  {
    id: 'aggressive',
    keys: ['B', 'R'],
    aria: 'B R',
    description: 'Bet or raise',
    group: 'Action',
    scope: 'panel',
  },
  {
    id: 'size',
    keys: DIGITS,
    keysLabel: '1–9',
    aria: DIGITS.join(' '),
    description: 'Bet or raise the n-th size',
    group: 'Size',
    scope: 'panel',
  },
  {
    id: 'customSize',
    keys: ['0'],
    aria: '0',
    description: 'Custom size',
    group: 'Size',
    scope: 'panel',
  },
  {
    id: 'value',
    keys: ['V'],
    aria: 'V',
    description: 'Intent: value',
    group: 'Intent',
    scope: 'panel',
  },
  {
    id: 'bluff',
    keys: ['L'],
    aria: 'L',
    description: 'Intent: bluff',
    group: 'Intent',
    scope: 'panel',
  },
  {
    id: 'semiBluff',
    keys: ['S'],
    aria: 'S',
    description: 'Intent: semi-bluff',
    group: 'Intent',
    scope: 'panel',
  },
  {
    id: 'next',
    keys: ['N'],
    aria: 'N',
    description: 'Next puzzle (while answering: press twice to skip)',
    group: 'Puzzle',
    scope: 'app',
  },
  {
    id: 'help',
    keys: ['?', 'H'],
    aria: 'Shift+? H',
    description: 'Show or hide shortcuts',
    group: 'Puzzle',
    scope: 'app',
  },
  {
    id: 'escape',
    keys: ['Esc'],
    aria: 'Escape',
    description: 'Close, cancel a skip, or leave a field',
    group: 'Puzzle',
    scope: 'app',
  },
]

const BY_ID = new Map(SHORTCUTS.map((s) => [s.id, s]))

/** The table entry for a command. */
export function shortcut(id: ShortcutId): Shortcut {
  const s = BY_ID.get(id)
  if (!s) throw new Error(`unknown shortcut ${id}`)
  return s
}

const LETTERS: Record<string, ShortcutId> = {
  f: 'fold',
  x: 'check',
  c: 'call',
  b: 'aggressive',
  r: 'aggressive',
  v: 'value',
  l: 'bluff',
  s: 'semiBluff',
  e: 'focusEquity',
  a: 'focusRangeRead',
  n: 'next',
  h: 'help',
}

export interface KeyEventLike {
  key: string
  ctrlKey?: boolean
  altKey?: boolean
  metaKey?: boolean
  shiftKey?: boolean
  target: EventTarget | null
}

export interface ShortcutContext {
  enabled: boolean
}

const TEXT_INPUT_TYPES = new Set([
  'text',
  'number',
  'search',
  'email',
  'url',
  'tel',
  'password',
  'date',
  'time',
  'datetime-local',
  'month',
  'week',
])

function asElement(target: EventTarget | null): Element | null {
  return typeof Element !== 'undefined' && target instanceof Element ? target : null
}

/** True while the user is typing: text-like inputs, textareas, selects, contenteditable. */
export function isTypingTarget(target: EventTarget | null): boolean {
  const el = asElement(target)
  if (!el) return false
  if (el instanceof HTMLInputElement) return TEXT_INPUT_TYPES.has(el.type)
  if (el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) return true
  // jsdom has no `isContentEditable`, so read the attribute (inherited from ancestors)
  const editable = el.closest('[contenteditable]')
  return editable !== null && editable.getAttribute('contenteditable') !== 'false'
}

/**
 * Controls whose own Enter behaviour must win over the global submit. A range slider has none,
 * so Enter on it submits.
 */
function isFormControl(target: EventTarget | null): boolean {
  const el = asElement(target)
  if (!el) return false
  if (el instanceof HTMLInputElement && el.type === 'range') return false
  return el.closest('button, input, select, textarea, a[href], summary, [role="button"]') !== null
}

/** The command for a key press, or null when the key is not a shortcut here. */
export function keyToCommand(event: KeyEventLike, context: ShortcutContext): Command | null {
  if (!context.enabled) return null
  if (event.ctrlKey || event.altKey || event.metaKey) return null
  const { key } = event
  if (key === 'Escape') return { id: 'escape' }
  if (isTypingTarget(event.target)) return null
  if (key === 'Enter') return isFormControl(event.target) ? null : { id: 'submit' }
  if (key === '?' || (key === '/' && event.shiftKey)) return { id: 'help' }
  if (key === '0') return { id: 'customSize' }
  if (key.length === 1 && key >= '1' && key <= '9') return { id: 'size', n: Number(key) }
  const id = key.length === 1 ? LETTERS[key.toLowerCase()] : undefined
  return id ? { id } : null
}

/**
 * Calls `handler` for each shortcut pressed while `enabled`. The handler returns whether it
 * handled the command; handled keys get `preventDefault()` (so `E` never types an "e").
 */
export function useShortcuts(
  handler: (command: Command, event: KeyboardEvent) => boolean,
  enabled: boolean,
): void {
  const latest = useRef(handler)
  useLayoutEffect(() => {
    latest.current = handler
  })
  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (event: KeyboardEvent) => {
      const command = keyToCommand(event, { enabled })
      if (command && latest.current(command, event)) event.preventDefault()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled])
}
