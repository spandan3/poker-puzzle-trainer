import { useEffect, useId, useReducer, useRef, useSyncExternalStore } from 'react'
import type { CSSProperties, ChangeEvent, FormEvent, ReactNode, RefObject } from 'react'
import { flushSync } from 'react-dom'
import type { ActionView, AttemptIn, Intent, PlayActionChoice } from '../../api/types'
import type { ActionKind, AnswerErrors, AnswerField, AnswerState } from '../../lib/answer'
import {
  EMPTY_ANSWER,
  actionButtons,
  customBoundsBb,
  firstError,
  isAggressive,
  parsePercent,
  sizeOptions,
  validateAction,
  validateAnswer,
} from '../../lib/answer'
import { formatBb, bbToChips } from '../../lib/format'
import type { Command, ShortcutId } from '../../lib/shortcuts'
import { shortcut, useShortcuts } from '../../lib/shortcuts'
import styles from './AnswerPanel.module.css'

interface AnswerPanelBase {
  view: ActionView
  /** The draft resets when this changes. Default `view.id`; play passes one key per decision. */
  draftKey?: string | number
  /** a submit is in flight: submit is disabled and the answer can't be changed */
  busy: boolean
  /** the last submit's error (409 / 422 `formatDetail`), shown inline */
  error: string | null
  /** set after a 409 for this puzzle: the custom size box is disabled with this message */
  customDisabledReason: string | null
  /**
   * Single-key shortcuts on. The parent passes `shortcutsOn && !overlayOpen`, so keys never act
   * on the panel behind the shortcuts overlay (the overlay also swallows keys while open).
   */
  shortcutsOn: boolean
  /** a starting draft (the gallery and tests) */
  initial?: Partial<AnswerState>
}

/** A puzzle answer: an equity guess, a range read and an intent, sent with `onSubmit`. */
interface PuzzleAnswerProps extends AnswerPanelBase {
  guesses?: true
  /**
   * Called once per submit with the request body. The parent must respond by setting `busy`
   * (true while the request is in flight, then false): further submits are ignored until a
   * render with `busy` false after that.
   */
  onSubmit: (body: AttemptIn) => void
  onAct?: never
}

/** A play action: no guesses; the chosen option or custom size goes to `onAct`, once per submit. */
interface PlayActionProps extends AnswerPanelBase {
  guesses: false
  onAct: (body: PlayActionChoice) => void
  onSubmit?: never
}

export type AnswerPanelProps = PuzzleAnswerProps | PlayActionProps

/** The answer form. Its draft resets whenever `draftKey` (default `view.id`) changes. */
export function AnswerPanel(props: AnswerPanelProps) {
  return <Panel key={props.draftKey ?? props.view.id} {...props} />
}

type Msg =
  | { type: 'equity'; text: string }
  | { type: 'rangeRead'; text: string }
  | { type: 'skipRangeRead'; skipped: boolean }
  | { type: 'action'; kind: ActionKind }
  | { type: 'size'; index: number; kind: ActionKind }
  | { type: 'custom'; kind: ActionKind; text?: string }
  | { type: 'intent'; intent: Intent | null }

function reducer(state: AnswerState, msg: Msg): AnswerState {
  switch (msg.type) {
    case 'equity':
      return { ...state, equity: msg.text }
    case 'rangeRead':
      return { ...state, rangeRead: msg.text, rangeSkipped: false }
    case 'skipRangeRead':
      return { ...state, rangeSkipped: msg.skipped, rangeRead: msg.skipped ? '' : state.rangeRead }
    case 'action':
      if (isAggressive(msg.kind)) {
        // selecting the group keeps a size already chosen, and chooses none otherwise
        return isAggressive(state.action)
          ? { ...state, action: msg.kind }
          : { ...state, action: msg.kind, size: null }
      }
      return { ...state, action: msg.kind, size: null, intent: null }
    case 'size':
      return {
        ...state,
        action: msg.kind,
        size: msg.index,
        intent: isAggressive(state.action) ? state.intent : null,
      }
    case 'custom':
      return {
        ...state,
        action: msg.kind,
        size: 'custom',
        custom: msg.text ?? state.custom,
        intent: isAggressive(state.action) ? state.intent : null,
      }
    case 'intent':
      return { ...state, intent: msg.intent }
  }
}

/**
 * Below this viewport width the answer panel compacts so that its tallest state fits 1024×768
 * (the Puzzles height budget): size and intent buttons drop their key hints, the size chips pack
 * tighter, the custom size shows its bounds as the box's placeholder, "optional" is read but not
 * drawn, and the Range-read hint is shortened. The shortcuts all still work.
 */
const COMPACT_QUERY = '(width < 1100px)'

function subscribeCompact(onChange: () => void) {
  const query = window.matchMedia?.(COMPACT_QUERY)
  query?.addEventListener('change', onChange)
  return () => query?.removeEventListener('change', onChange)
}

function useNarrow(): boolean {
  return useSyncExternalStore(
    subscribeCompact,
    () => window.matchMedia?.(COMPACT_QUERY).matches ?? false,
    () => false,
  )
}

const RANGE_READ_HELP = "% of Villain's range you're ahead of now"
const RANGE_READ_HELP_SHORT = "% of range you're ahead of"

const INTENTS: { intent: Intent; label: string; shortcut: ShortcutId }[] = [
  { intent: 'value', label: 'Value', shortcut: 'value' },
  { intent: 'bluff', label: 'Bluff', shortcut: 'bluff' },
  { intent: 'semi_bluff', label: 'Semi-bluff', shortcut: 'semiBluff' },
]

const ACTION_SHORTCUT: Record<ActionKind, ShortcutId> = {
  fold: 'fold',
  check: 'check',
  call: 'call',
  bet: 'aggressive',
  raise: 'aggressive',
}

const FIX_FIELD: Partial<Record<AnswerField, string>> = {
  equity: 'Fix the equity estimate',
  rangeRead: 'Fix the range read',
  custom: 'Fix the custom size',
}

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className={styles.kbd} aria-hidden="true">
      {children}
    </kbd>
  )
}

interface Hint {
  attrs: Record<string, string>
  kbd: ReactNode
}

const NO_HINT: Hint = { attrs: {}, kbd: null }

/** A hint that keeps its attributes (`aria-keyshortcuts`) but draws no key. */
const NO_HINT_WITH_ATTRS = (h: Hint): Hint => ({ attrs: h.attrs, kbd: null })

/**
 * The <kbd> hint and `aria-keyshortcuts` for a control, from `SHORTCUTS` (none when shortcuts
 * are off). `key` picks the key shown (default: the first); `aria` overrides the attribute.
 */
function makeHint(on: boolean) {
  return (id: ShortcutId, opts: { key?: string; aria?: string } = {}): Hint => {
    if (!on) return NO_HINT
    const s = shortcut(id)
    return {
      attrs: { 'data-shortcut': id, 'aria-keyshortcuts': opts.aria ?? opts.key ?? s.aria },
      kbd: <Kbd>{opts.key ?? s.keys[0]}</Kbd>,
    }
  }
}

const ACTION_HINT: Partial<Record<ActionKind, { key: string; aria: string }>> = {
  bet: { key: 'B', aria: 'B R' },
  raise: { key: 'R', aria: 'R B' },
}

function Panel({
  view,
  onSubmit,
  guesses = true,
  onAct,
  busy,
  error,
  customDisabledReason,
  shortcutsOn,
  initial,
}: AnswerPanelProps) {
  const [state, rawDispatch] = useReducer(reducer, { ...EMPTY_ANSWER, ...initial })
  // nothing changes the answer while a submit is in flight: clicks, typing and shortcuts alike
  const dispatch = (msg: Msg) => {
    if (!busy) rawDispatch(msg)
  }
  const formRef = useRef<HTMLFormElement>(null)
  const equityRef = useRef<HTMLInputElement>(null)
  const rangeRef = useRef<HTMLInputElement>(null)
  const customRef = useRef<HTMLInputElement>(null)
  // one request per submit: repeats are ignored until the parent reports `busy` done
  const lockRef = useRef(false)
  useEffect(() => {
    if (!busy) lockRef.current = false
  })

  // puzzles only: Play has the height to spare, so it keeps the roomy layout
  const compact = useNarrow() && guesses
  const ids = useId()
  const reasonId = `${ids}-reason`
  const hint = makeHint(shortcutsOn)

  const buttons = actionButtons(view)
  const aggressiveKind = buttons.find((b) => b.enabled && isAggressive(b.kind))?.kind ?? null
  const sizes = sizeOptions(view)
  const bounds = customBoundsBb(view)
  const customDisabled = customDisabledReason !== null
  const aggressive = isAggressive(state.action)
  const full = guesses ? validateAnswer(state, view, { customDisabled }) : null
  const act = guesses ? null : validateAction(state, view, { customDisabled })
  const result = full ?? act!
  const errors: AnswerErrors = result.ok ? {} : result.errors

  // inline errors: only for text the user typed
  const inline: AnswerErrors = {}
  if (state.equity.trim() !== '' && errors.equity) inline.equity = errors.equity
  if (state.rangeRead.trim() !== '' && errors.rangeRead) inline.rangeRead = errors.rangeRead
  if (state.custom.trim() !== '' && errors.custom && !customDisabled) inline.custom = errors.custom

  let reason: string | null = null
  if (!result.ok) {
    const field = (Object.keys(inline) as AnswerField[])[0]
    reason = field ? (FIX_FIELD[field] ?? null) : (firstError(errors) ?? null)
  }

  const select = (kind: ActionKind) => {
    if (buttons.find((b) => b.kind === kind)?.enabled) dispatch({ type: 'action', kind })
  }

  // A shortcut that changes the action moves focus along if it sits on another action button,
  // so the focused button and the selected one never differ (two "selected-looking" buttons).
  const selectByKey = (kind: ActionKind) => {
    select(kind)
    const active = document.activeElement
    if (active instanceof HTMLElement && active.closest('[role="group"][aria-label="Action"]')) {
      const next = formRef.current?.querySelector<HTMLElement>(
        `[role="group"][aria-label="Action"] [data-kind="${kind}"]:not([aria-disabled="true"])`,
      )
      if (next && next !== active) next.focus()
    }
  }

  // the custom size group, at the end of the size row
  const customSize =
    bounds && aggressiveKind ? (
      <CustomSize
        id={`${ids}-custom`}
        bounds={bounds}
        compact={compact}
        text={state.custom}
        selected={state.size === 'custom'}
        disabledReason={customDisabledReason}
        error={inline.custom ?? null}
        inputRef={customRef}
        hint={compact ? NO_HINT_WITH_ATTRS(hint('customSize')) : hint('customSize')}
        onChange={(text) => dispatch({ type: 'custom', kind: aggressiveKind, text })}
      />
    ) : null

  const focusCustom = () => {
    if (!bounds || customDisabled || !aggressiveKind) return false
    flushSync(() => dispatch({ type: 'custom', kind: aggressiveKind }))
    customRef.current?.focus()
    return true
  }

  const onCommand = (cmd: Command): boolean => {
    if (cmd.id === 'next' || cmd.id === 'help') return false
    if (cmd.id === 'escape') {
      const active = document.activeElement
      if (active instanceof HTMLElement && formRef.current?.contains(active)) {
        active.blur()
        return true
      }
      return false
    }
    // nothing changes the answer while a submit is in flight
    if (busy) return true
    switch (cmd.id) {
      case 'fold':
      case 'check':
      case 'call':
        selectByKey(cmd.id)
        return true
      case 'aggressive':
        if (aggressiveKind) selectByKey(aggressiveKind)
        return true
      case 'size': {
        const size = sizes[(cmd.n ?? 0) - 1]
        if (size && aggressiveKind) {
          dispatch({ type: 'size', index: size.index, kind: aggressiveKind })
        }
        return true
      }
      case 'customSize':
        return focusCustom()
      case 'value':
      case 'bluff':
      case 'semiBluff': {
        if (!guesses || !aggressive) return false
        const intent = INTENTS.find((i) => i.shortcut === cmd.id)?.intent ?? null
        dispatch({ type: 'intent', intent })
        return true
      }
      case 'focusEquity':
        if (!guesses) return false
        equityRef.current?.focus()
        return true
      case 'focusRangeRead':
        if (!guesses || !view.range_read_asked) return false
        flushSync(() => dispatch({ type: 'skipRangeRead', skipped: false }))
        rangeRef.current?.focus()
        return true
      case 'submit':
        formRef.current?.requestSubmit()
        return true
    }
  }
  useShortcuts(onCommand, shortcutsOn)

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (busy || lockRef.current) return
    if (full?.ok) {
      lockRef.current = true
      onSubmit?.(full.body)
    } else if (act?.ok) {
      lockRef.current = true
      onAct?.(act.body)
    }
  }

  return (
    <form
      ref={formRef}
      className={styles.panel}
      data-compact={compact || undefined}
      aria-label="Your answer"
      aria-busy={busy || undefined}
      onSubmit={handleSubmit}
      noValidate
    >
      {guesses && (view.attempts_so_far ?? 0) > 0 && (
        <p className={styles.practice} data-testid="practice-note">
          Practice — this attempt won&apos;t count toward your stats.
        </p>
      )}
      {guesses && (
        <div className={styles.estimates}>
          <PercentField
            label="Equity"
            help="vs Villain's range"
            slider="Equity slider"
            text={state.equity}
            error={inline.equity ?? null}
            inputRef={equityRef}
            hint={hint('focusEquity')}
            onChange={(text) => dispatch({ type: 'equity', text })}
          />
          {view.range_read_asked && (
            <PercentField
              label="Range read"
              help={RANGE_READ_HELP}
              shortHelp={compact ? RANGE_READ_HELP_SHORT : undefined}
              slider="Range read slider"
              text={state.rangeRead}
              skipped={state.rangeSkipped}
              error={inline.rangeRead ?? null}
              inputRef={rangeRef}
              hint={hint('focusRangeRead')}
              onChange={(text) => dispatch({ type: 'rangeRead', text })}
              onSkip={(skipped) => {
                flushSync(() => dispatch({ type: 'skipRangeRead', skipped }))
                if (!skipped) rangeRef.current?.focus()
              }}
            />
          )}
        </div>
      )}

      <div
        className={styles.actions}
        role="group"
        aria-label="Action"
        data-divided={guesses || undefined}
      >
        {buttons.map((b) => {
          const h = hint(ACTION_SHORTCUT[b.kind], ACTION_HINT[b.kind])
          const pressed = state.action === b.kind
          const [verb, ...amount] = b.label.split(' ')
          return (
            <button
              key={b.kind}
              type="button"
              className={styles.action}
              data-kind={b.kind}
              aria-pressed={pressed}
              aria-disabled={b.enabled ? undefined : true}
              onClick={() => select(b.kind)}
              {...h.attrs}
            >
              <span className={styles.actionLabel}>
                {verb}
                {amount.length > 0 && (
                  <>
                    {' '}
                    <span className={styles.actionAmount}>{amount.join(' ')}</span>
                  </>
                )}
              </span>
              {h.kbd}
            </button>
          )
        })}
      </div>

      {aggressive && aggressiveKind && (
        <div className={styles.sizeRow}>
          <div className={styles.sizes} role="group" aria-label="Size">
            {sizes.map((s, i) => {
              const key = String(i + 1)
              const h = i < 9 ? hint('size', { key }) : NO_HINT
              // compact: the digit keys still work (aria-keyshortcuts), the hint is not drawn
              const shown = compact ? { ...h, kbd: null } : h
              const [name, amount] = s.label.split(' · ')
              return (
                <button
                  key={s.index}
                  type="button"
                  className={styles.size}
                  data-size-label={s.label}
                  aria-label={s.label}
                  aria-pressed={state.size === s.index}
                  onClick={() => dispatch({ type: 'size', index: s.index, kind: aggressiveKind })}
                  {...h.attrs}
                >
                  <span className={styles.sizeName}>{name}</span>
                  <span className={styles.sizeSep}> · </span>
                  <span className={styles.sizeAmount}>{amount}</span>
                  {shown.kbd}
                </button>
              )
            })}
          </div>
          {customSize}
        </div>
      )}

      <div className={styles.footer}>
        {guesses && aggressive ? (
          <div className={styles.intent} role="group" aria-label="Intent">
            <span className={styles.intentLabel} aria-hidden="true">
              Intent
            </span>
            {INTENTS.map((i) => {
              const h = compact ? NO_HINT_WITH_ATTRS(hint(i.shortcut)) : hint(i.shortcut)
              const pressed = state.intent === i.intent
              return (
                <button
                  key={i.intent}
                  type="button"
                  className={styles.intentButton}
                  data-intent={i.intent}
                  aria-pressed={pressed}
                  onClick={() => dispatch({ type: 'intent', intent: pressed ? null : i.intent })}
                  {...h.attrs}
                >
                  {i.label}
                  {h.kbd}
                </button>
              )
            })}
            <span className={compact ? styles.srOnly : styles.optional}>optional</span>
          </div>
        ) : (
          <div className={styles.footerSpacer} />
        )}

        <div className={styles.submitArea}>
          <div className={styles.messages}>
            {/* in the footer, next to Submit, so an error never makes the panel taller */}
            {error !== null && (
              <p className={styles.error} role="alert">
                {error}
              </p>
            )}
            <p
              id={reasonId}
              className={styles.reason}
              data-ready={result.ok || undefined}
              data-behind-error={error !== null || undefined}
              aria-live="polite"
            >
              {busy ? 'Submitting…' : (reason ?? 'Ready to submit')}
            </p>
          </div>
          <button
            type="submit"
            className={styles.submit}
            disabled={busy || !result.ok}
            aria-describedby={reasonId}
            {...hint('submit').attrs}
          >
            {busy ? 'Submitting…' : 'Submit'}
            {hint('submit').kbd}
          </button>
        </div>
      </div>
    </form>
  )
}

function PercentField(props: {
  label: string
  help: string
  /** A shorter text drawn in place of `help`; `help` stays as the input's description. */
  shortHelp?: string
  slider: string
  text: string
  error: string | null
  skipped?: boolean
  inputRef: RefObject<HTMLInputElement | null>
  hint: Hint
  onChange: (text: string) => void
  onSkip?: (skipped: boolean) => void
}) {
  const { label, help, shortHelp, slider, text, error, skipped, inputRef, hint, onChange, onSkip } =
    props
  const id = useId()
  const parsed = parsePercent(text)
  const value = typeof parsed === 'number' ? parsed : null
  const fromSlider = (e: ChangeEvent<HTMLInputElement>) => onChange(e.currentTarget.value)
  return (
    <div
      className={styles.field}
      data-shortcut-scope=""
      data-skipped={skipped || undefined}
      data-invalid={error !== null || undefined}
    >
      <div className={styles.fieldHead}>
        <label htmlFor={`${id}-text`} className={styles.fieldLabel}>
          {label}
          {hint.kbd}
        </label>
        {shortHelp === undefined ? (
          <span id={`${id}-help`} className={styles.fieldHelp}>
            {help}
          </span>
        ) : (
          <>
            <span className={styles.fieldHelp} aria-hidden="true">
              {shortHelp}
            </span>
            <span id={`${id}-help`} className={styles.srOnly}>
              {help}
            </span>
          </>
        )}
        {onSkip && (
          <button
            type="button"
            className={styles.skip}
            aria-pressed={skipped ?? false}
            aria-label="Skip range read"
            onClick={() => onSkip(!skipped)}
          >
            Skip
          </button>
        )}
      </div>
      <div className={styles.fieldControls}>
        <input
          type="range"
          className={styles.slider}
          min={0}
          max={100}
          step={1}
          value={value ?? 50}
          aria-label={slider}
          aria-valuetext={value === null ? 'not set' : `${value}%`}
          data-unset={value === null || undefined}
          style={{ '--fill': `${value ?? 0}%` } as CSSProperties}
          onChange={fromSlider}
          onClick={(e) => {
            if (value === null) onChange(e.currentTarget.value)
          }}
        />
        <span className={styles.percentBox}>
          <input
            ref={inputRef}
            id={`${id}-text`}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            className={styles.percentInput}
            value={text}
            placeholder="–"
            aria-invalid={error !== null || undefined}
            aria-describedby={error ? `${id}-help ${id}-error` : `${id}-help`}
            onChange={(e) => onChange(e.currentTarget.value)}
            {...hint.attrs}
          />
          <span className={styles.percentSign} aria-hidden="true">
            %
          </span>
        </span>
      </div>
      {/* always present, so the live region exists before its message arrives */}
      <p id={`${id}-error`} className={styles.fieldError} aria-live="polite">
        {error}
      </p>
    </div>
  )
}

function CustomSize(props: {
  id: string
  bounds: { min: number; max: number }
  /** the bounds are the box's placeholder and title, not text beside it */
  compact: boolean
  text: string
  selected: boolean
  disabledReason: string | null
  error: string | null
  inputRef: RefObject<HTMLInputElement | null>
  hint: Hint
  onChange: (text: string) => void
}) {
  const { id, bounds, compact, text, selected, disabledReason, error, inputRef, hint, onChange } =
    props
  const disabled = disabledReason !== null
  const low = formatBb(bbToChips(bounds.min)).replace(' bb', '')
  const range = `${low}–${formatBb(bbToChips(bounds.max))}`
  const shortRange = `${low}–${formatBb(bbToChips(bounds.max)).replace(' bb', '')}`
  const describedBy = [`${id}-bounds`, error && `${id}-error`, disabled && `${id}-disabled`]
    .filter(Boolean)
    .join(' ')
  return (
    <div
      className={styles.custom}
      data-shortcut-scope=""
      data-selected={(selected && !disabled) || undefined}
      data-invalid={error !== null || undefined}
      data-disabled={disabled || undefined}
      data-compact={compact || undefined}
    >
      <label htmlFor={id} className={styles.customLabel}>
        to {/* the bounds beside the box show the unit */}
        <span className={styles.srOnly}>(bb)</span>
        {hint.kbd}
      </label>
      <input
        ref={inputRef}
        id={id}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        className={styles.customInput}
        value={text}
        disabled={disabled}
        placeholder={disabled ? 'off' : compact ? `${shortRange} bb` : 'custom'}
        title={disabledReason ?? (compact ? range : undefined)}
        aria-invalid={error !== null || undefined}
        aria-describedby={describedBy}
        onChange={(e) => onChange(e.currentTarget.value)}
        {...hint.attrs}
      />
      <span id={`${id}-bounds`} className={compact ? styles.srOnly : styles.customBounds}>
        {range}
      </span>
      {/* always present, so the live region exists before its message arrives */}
      <p id={`${id}-error`} className={styles.fieldError} aria-live="polite">
        {error}
      </p>
      {disabled && (
        // read with the box; shown once, as the submit error, rather than twice
        <p id={`${id}-disabled`} className={styles.srOnly}>
          {disabledReason}
        </p>
      )}
    </div>
  )
}
