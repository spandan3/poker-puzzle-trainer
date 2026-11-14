// The puzzle flow: a reducer over the API. Load (resume or new), answer, submit, result, next.
import { useCallback, useEffect, useLayoutEffect, useReducer, useRef, useState } from 'react'
import * as client from '../api/client'
import { ApiError } from '../api/client'
import type {
  AttemptIn,
  AttemptResult,
  PuzzleView,
  SettingsPatch,
  SettingsView,
  StreetName,
} from '../api/types'
import { STREET_ORDER } from '../lib/history'

/** The parts of the API client the flow uses (injectable for tests). */
export type FlowApi = Pick<
  typeof client,
  | 'currentPuzzle'
  | 'newPuzzle'
  | 'getPuzzle'
  | 'getAttempt'
  | 'submitAttempt'
  | 'getSettings'
  | 'patchSettings'
>

/** What was on screen before a load or an error: kept so the page doesn't collapse. */
export interface Shown {
  view: PuzzleView
  result: AttemptResult | null
}

export type FlowState =
  | { kind: 'loading'; previous: Shown | null }
  | {
      kind: 'answering'
      view: PuzzleView
      error: string | null
      customDisabledReason: string | null
      skipPending: boolean
    }
  | { kind: 'submitting'; view: PuzzleView; customDisabledReason: string | null }
  | { kind: 'result'; view: PuzzleView; result: AttemptResult }
  | { kind: 'error'; message: string; retry: () => void; previous: Shown | null }

export interface PuzzleFlow {
  state: FlowState
  settings: SettingsView | null
  /** A failed settings save (the change is reverted), shown as a dismissable warning. */
  notice: string | null
  dismissNotice: () => void
  street: StreetName | null
  setStreet: (street: StreetName | null) => void
  /** Loads a new puzzle now (after a result, or a confirmed skip). Ignored while one loads. */
  newPuzzle: () => void
  /**
   * Replays a stored puzzle (from history): answering state, a practice attempt. `false` when
   * ignored because a load or a submit is in flight (nothing was opened).
   */
  openPuzzle: (id: number) => boolean
  /**
   * Reopens a stored attempt's result (from history). "Next puzzle" works as after a submit.
   * `false` when ignored, as for `openPuzzle`.
   */
  openAttempt: (attemptId: number) => boolean
  /** `N`: next after a result; while answering, asks first and skips on the second press. */
  requestSkip: () => void
  cancelSkip: () => void
  submit: (body: AttemptIn) => void
  /** Saves a setting (optimistic); resolves true when the server saved it. */
  setSetting: (patch: SettingsPatch) => Promise<boolean>
}

/** The second `N` must come within this long of the first. */
export const SKIP_CONFIRM_MS = 3000

export const GENERATION_FAILED = "Couldn't generate a puzzle — try again"
export const SETTINGS_FAILED = "Couldn't save the setting — it was changed back"
const STREET_KEY = 'ppt.street'

/** The 409 that disables custom sizes (the backend's STALE_MODEL message starts so). */
export function isStaleModel(error: ApiError): boolean {
  return (
    error.status === 409 &&
    typeof error.detail === 'string' &&
    error.detail.startsWith('Villain model changed')
  )
}

function loadMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 503) return GENERATION_FAILED
    if (error.status === 0) return "Can't reach the server. Check it is running, then retry."
    return `Couldn't load a puzzle: ${error.message}`
  }
  return "Couldn't load a puzzle"
}

function openMessage(error: unknown, noun: string): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return "Can't reach the server. Check it is running, then retry."
    if (error.status === 404) return `That ${noun} isn't stored any more.`
    return `Couldn't open the ${noun}: ${error.message}`
  }
  return `Couldn't open the ${noun}`
}

function submitMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409 || error.status === 422) return error.message
    if (error.status === 0) return "Couldn't reach the server. Your answer is kept: submit again."
    return `Couldn't submit (${error.message}). Your answer is kept: submit again.`
  }
  return "Couldn't submit. Your answer is kept: submit again."
}

function readStreet(): StreetName | null {
  try {
    const value = window.localStorage.getItem(STREET_KEY)
    return value !== null && (STREET_ORDER as readonly string[]).includes(value)
      ? (value as StreetName)
      : null
  } catch {
    return null
  }
}

function writeStreet(street: StreetName | null): void {
  try {
    if (street === null) window.localStorage.removeItem(STREET_KEY)
    else window.localStorage.setItem(STREET_KEY, street)
  } catch {
    // storage blocked: the choice lasts for this page only
  }
}

function shownOf(state: FlowState): Shown | null {
  switch (state.kind) {
    case 'answering':
    case 'submitting':
      return { view: state.view, result: null }
    case 'result':
      return { view: state.view, result: state.result }
    case 'loading':
    case 'error':
      return state.previous
  }
}

type Msg =
  | { type: 'loading' }
  | { type: 'loaded'; view: PuzzleView }
  | { type: 'opened'; view: PuzzleView; result: AttemptResult }
  | { type: 'loadFailed'; message: string; retry: () => void }
  | { type: 'submitting' }
  | { type: 'submitted'; result: AttemptResult }
  | { type: 'submitFailed'; error: string; disableCustom: string | null }
  | { type: 'skipPending'; pending: boolean }

function reducer(state: FlowState, msg: Msg): FlowState {
  switch (msg.type) {
    case 'loading':
      return { kind: 'loading', previous: shownOf(state) }
    case 'loaded':
      return {
        kind: 'answering',
        view: msg.view,
        error: null,
        customDisabledReason: null,
        skipPending: false,
      }
    case 'opened':
      return { kind: 'result', view: msg.view, result: msg.result }
    case 'loadFailed':
      return { kind: 'error', message: msg.message, retry: msg.retry, previous: shownOf(state) }
    case 'submitting':
      if (state.kind !== 'answering') return state
      return {
        kind: 'submitting',
        view: state.view,
        customDisabledReason: state.customDisabledReason,
      }
    case 'submitted':
      if (state.kind !== 'submitting') return state
      return { kind: 'result', view: state.view, result: msg.result }
    case 'submitFailed':
      if (state.kind !== 'submitting') return state
      return {
        kind: 'answering',
        view: state.view,
        error: msg.error,
        customDisabledReason: msg.disableCustom ?? state.customDisabledReason,
        skipPending: false,
      }
    case 'skipPending':
      if (state.kind !== 'answering') return state
      return { ...state, skipPending: msg.pending }
  }
}

const INITIAL: FlowState = { kind: 'loading', previous: null }

export interface FlowOptions {
  /**
   * Whether the first puzzle may load (default true). The page switch sets it false while the
   * Progress page is the landing page, so opening Progress never generates a puzzle; once true it
   * stays loaded.
   */
  enabled?: boolean
}

export function usePuzzleFlow(
  api: FlowApi = client,
  { enabled = true }: FlowOptions = {},
): PuzzleFlow {
  const [state, dispatch] = useReducer(reducer, INITIAL)
  const [settings, setSettings] = useState<SettingsView | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [street, setStreetState] = useState<StreetName | null>(readStreet)

  // the latest values, for callbacks that must not go stale between renders
  const stateRef = useRef(state)
  const streetRef = useRef(street)
  const settingsRef = useRef(settings)
  useLayoutEffect(() => {
    stateRef.current = state
    streetRef.current = street
    settingsRef.current = settings
  })

  // one load at a time; a second `N` or click while one is in flight does nothing
  const loadingRef = useRef(false)
  const startedRef = useRef(false)
  const submittingRef = useRef(false)
  const skipTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const saveSeq = useRef(0)
  const lastSave = useRef(new Map<string, number>())

  const clearSkipTimer = () => {
    if (skipTimer.current !== null) clearTimeout(skipTimer.current)
    skipTimer.current = null
  }

  const load = useCallback(
    (resume: boolean) => {
      const attempt = () => {
        if (loadingRef.current) return
        loadingRef.current = true
        clearSkipTimer()
        dispatch({ type: 'loading' })
        const run = async (): Promise<PuzzleView> => {
          const current = resume ? await api.currentPuzzle() : null
          return current ?? (await api.newPuzzle({ street: streetRef.current }))
        }
        run()
          .then((view) => dispatch({ type: 'loaded', view }))
          .catch((error: unknown) =>
            dispatch({ type: 'loadFailed', message: loadMessage(error), retry: attempt }),
          )
          .finally(() => {
            loadingRef.current = false
          })
      }
      attempt()
    },
    [api],
  )

  // One load of a stored puzzle or attempt (history). Like `load`: one at a time, errors go to the
  // error state with a Retry. Opening one also counts as the first load, so a landing page that
  // later shows Puzzles doesn't load (and replace) another puzzle on top of it.
  const open = useCallback(
    (
      fetchView: () => Promise<{ view: PuzzleView; result: AttemptResult | null }>,
      noun: string,
    ): boolean => {
      const attempt = (): boolean => {
        if (loadingRef.current) return false
        loadingRef.current = true
        startedRef.current = true
        clearSkipTimer()
        dispatch({ type: 'loading' })
        fetchView()
          .then(({ view, result }) =>
            dispatch(result ? { type: 'opened', view, result } : { type: 'loaded', view }),
          )
          .catch((error: unknown) =>
            dispatch({
              type: 'loadFailed',
              message: openMessage(error, noun),
              retry: () => void attempt(),
            }),
          )
          .finally(() => {
            loadingRef.current = false
          })
        return true
      }
      return attempt()
    },
    [],
  )

  const openPuzzle = useCallback(
    (id: number) => {
      if (stateRef.current.kind === 'submitting') return false
      return open(async () => ({ view: await api.getPuzzle(id), result: null }), 'puzzle')
    },
    [api, open],
  )

  const openAttempt = useCallback(
    (attemptId: number) => {
      if (stateRef.current.kind === 'submitting') return false
      return open(async () => {
        const result = await api.getAttempt(attemptId)
        return { view: await api.getPuzzle(result.attempt.puzzle_id), result }
      }, 'result')
    },
    [api, open],
  )

  // Initial load, once: the flags are never reset in cleanup and the request is never aborted, so
  // StrictMode's double effect sends one GET (and at most one POST). Settings load at once; the
  // puzzle waits for `enabled`.
  const settingsStarted = useRef(false)
  useEffect(() => {
    if (settingsStarted.current) return
    settingsStarted.current = true
    api.getSettings().then(setSettings, () => {
      // settings are optional for play: the controls keep their defaults
    })
  }, [api])

  useEffect(() => {
    if (!enabled || startedRef.current) return
    startedRef.current = true
    load(true)
  }, [enabled, load])

  useEffect(() => clearSkipTimer, [])

  const newPuzzle = useCallback(() => {
    if (stateRef.current.kind === 'submitting') return
    load(false)
  }, [load])

  const cancelSkip = useCallback(() => {
    clearSkipTimer()
    dispatch({ type: 'skipPending', pending: false })
  }, [])

  const requestSkip = useCallback(() => {
    const current = stateRef.current
    if (current.kind === 'result') {
      newPuzzle()
    } else if (current.kind === 'answering') {
      if (current.skipPending) {
        newPuzzle()
      } else {
        clearSkipTimer()
        dispatch({ type: 'skipPending', pending: true })
        skipTimer.current = setTimeout(() => {
          skipTimer.current = null
          dispatch({ type: 'skipPending', pending: false })
        }, SKIP_CONFIRM_MS)
      }
    }
    // loading, submitting, error: nothing to skip
  }, [newPuzzle])

  const submit = useCallback(
    (body: AttemptIn) => {
      const current = stateRef.current
      if (current.kind !== 'answering' || submittingRef.current) return
      submittingRef.current = true
      clearSkipTimer()
      dispatch({ type: 'submitting' })
      api
        .submitAttempt(current.view.id, body)
        .then((result) => dispatch({ type: 'submitted', result }))
        .catch((error: unknown) =>
          dispatch({
            type: 'submitFailed',
            error: submitMessage(error),
            disableCustom: error instanceof ApiError && isStaleModel(error) ? error.message : null,
          }),
        )
        .finally(() => {
          submittingRef.current = false
        })
    },
    [api],
  )

  // Optimistic: the control changes at once; a failed save puts it back and says so.
  const setSetting = useCallback(
    (patch: SettingsPatch): Promise<boolean> => {
      const before = settingsRef.current
      if (before) setSettings({ ...before, ...patch })
      setNotice(null)
      // a newer save of the same field wins: an older one's failure must not revert it
      const keys = Object.keys(patch)
      const seq = ++saveSeq.current
      for (const key of keys) lastSave.current.set(key, seq)
      const latest = () => keys.some((key) => lastSave.current.get(key) === seq)
      return api.patchSettings(patch).then(
        (view) => {
          if (latest()) setSettings(view)
          return true
        },
        () => {
          if (!latest()) return false
          setSettings((now) => (now && before ? { ...now, ...pick(before, patch) } : now))
          setNotice(SETTINGS_FAILED)
          return false
        },
      )
    },
    [api],
  )

  const setStreet = useCallback((value: StreetName | null) => {
    setStreetState(value)
    writeStreet(value)
  }, [])

  const dismissNotice = useCallback(() => setNotice(null), [])

  return {
    state,
    settings,
    notice,
    dismissNotice,
    street,
    setStreet,
    newPuzzle,
    openPuzzle,
    openAttempt,
    requestSkip,
    cancelSkip,
    submit,
    setSetting,
  }
}

/** The fields of `from` named by `patch` (to revert exactly what a failed patch changed). */
function pick(from: SettingsView, patch: SettingsPatch): Partial<SettingsView> {
  const out: Partial<SettingsView> = {}
  for (const key of Object.keys(patch) as (keyof SettingsPatch)[]) {
    ;(out as Record<string, unknown>)[key] = from[key]
  }
  return out
}
