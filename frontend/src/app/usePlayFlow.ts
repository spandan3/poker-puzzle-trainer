// The play flow: a cash-game session against one bot. It owns the session and the reveal: when a
// response arrives, the bot's new actions appear one at a time (`BOT_PAUSE_MS` apart) and Hero's
// controls wait until they have all been shown.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import * as client from '../api/client'
import { ApiError } from '../api/client'
import type { PlayActionChoice, PlaySessionSummary, PlaySessionView } from '../api/types'

/** The parts of the API client the flow uses (injectable for tests). */
export type PlayApi = Pick<
  typeof client,
  | 'currentPlaySession'
  | 'startPlaySession'
  | 'endPlaySession'
  | 'nextPlayHand'
  | 'playAction'
  | 'listPlaySessions'
>

/** How long each of the bot's actions stays on screen before the next one appears. */
export const BOT_PAUSE_MS = 600

export type PlayState =
  | { kind: 'loading' }
  /** no open session: the start panel */
  | { kind: 'idle' }
  /** a hand is running (Hero to act, or the bot's actions being revealed) */
  | { kind: 'playing' }
  /** the hand is over and its last action has been shown */
  | { kind: 'handOver' }
  /** a request failed; what was on screen stays */
  | { kind: 'error'; message: string; retry: () => void }

export interface PlayFlow {
  state: PlayState
  /** The open session, or null (idle and the first load). */
  session: PlaySessionView | null
  /** Past sessions for the start panel (null until loaded). */
  past: PlaySessionSummary[] | null
  /** How many of the hand's history entries are on screen. */
  shownCount: number
  /** The bot's actions are still being shown: Hero's controls wait. */
  revealing: boolean
  /** A request is in flight. */
  busy: boolean
  start: () => void
  /** Hero acts: ignored while revealing or while a request is in flight. */
  act: (choice: PlayActionChoice) => void
  nextHand: (topUp: boolean) => void
  end: () => void
  retry: () => void
}

export interface PlayFlowOptions {
  /** Whether the first load may happen (default true). Once true it stays loaded. */
  enabled?: boolean
}

type Mode =
  /** a session loaded or reloaded: everything is shown at once */
  | 'whole'
  /** a new hand: the bot's first actions (if it acts first) are revealed from the start */
  | 'fromStart'
  /** after Hero's action: Hero's own entry is already shown, the bot's follow */
  | 'afterHero'

function errorMessage(error: unknown, what: string): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return "Can't reach the server. Check it is running, then retry."
    return `${what}: ${error.message}`
  }
  return what
}

interface Failure {
  message: string
}

export function usePlayFlow(
  api: PlayApi = client,
  { enabled = true }: PlayFlowOptions = {},
): PlayFlow {
  const [session, setSession] = useState<PlaySessionView | null>(null)
  const [past, setPast] = useState<PlaySessionSummary[] | null>(null)
  const [shownCount, setShownCount] = useState(0)
  const [loaded, setLoaded] = useState(false)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [busy, setBusy] = useState(false)

  const total = session?.hand?.table.history.length ?? 0
  const revealing = shownCount < total

  // the latest values, for callbacks that must not go stale between renders
  const sessionRef = useRef(session)
  const revealingRef = useRef(revealing)
  useLayoutEffect(() => {
    sessionRef.current = session
    revealingRef.current = revealing
  })
  const busyRef = useRef(false)
  const startedRef = useRef(false)

  // The bot's actions, one at a time.
  useEffect(() => {
    if (shownCount >= total) return
    const timer = setTimeout(() => setShownCount((n) => Math.min(n + 1, total)), BOT_PAUSE_MS)
    return () => clearTimeout(timer)
  }, [shownCount, total])

  const refreshPast = useCallback(() => {
    api.listPlaySessions().then(setPast, () => setPast((old) => old ?? []))
  }, [api])

  const apply = useCallback(
    (view: PlaySessionView | null, mode: Mode) => {
      setLoaded(true)
      if (view === null || !view.open) {
        setSession(null)
        setShownCount(0)
        refreshPast()
        return
      }
      const length = view.hand?.table.history.length ?? 0
      setShownCount((old) => {
        if (mode === 'whole') return length
        if (mode === 'fromStart') return 0
        const before = sessionRef.current?.hand?.action_count ?? old
        return Math.min(before + 1, length)
      })
      setSession(view)
    },
    [refreshPast],
  )

  const reloadNow = useCallback(async () => {
    apply(await api.currentPlaySession(), 'whole')
  }, [api, apply])

  // One request at a time. A 409 means the client's picture was stale (a doubled click, another
  // tab): load what the server has. Any other failure keeps what is on screen and offers a retry.
  const request = useCallback(
    async (call: () => Promise<PlaySessionView | null>, mode: Mode, what: string) => {
      if (busyRef.current) return
      busyRef.current = true
      setBusy(true)
      setFailure(null)
      try {
        try {
          apply(await call(), mode)
        } catch (error) {
          if (!(error instanceof ApiError && error.status === 409)) throw error
          await reloadNow()
        }
      } catch (error) {
        setLoaded(true)
        setFailure({ message: errorMessage(error, what) })
      } finally {
        busyRef.current = false
        setBusy(false)
      }
    },
    [apply, reloadNow],
  )

  const retry = useCallback(() => {
    void request(() => api.currentPlaySession(), 'whole', "Couldn't load the session")
  }, [api, request])

  // Initial load, once (StrictMode's second effect run is a no-op).
  useEffect(() => {
    if (!enabled || startedRef.current) return
    startedRef.current = true
    retry()
  }, [enabled, retry])

  const start = useCallback(() => {
    if (sessionRef.current !== null) return
    void request(() => api.startPlaySession(), 'fromStart', "Couldn't start a session")
  }, [api, request])

  const act = useCallback(
    (choice: PlayActionChoice) => {
      const hand = sessionRef.current?.hand
      if (!hand || hand.status !== 'in_progress' || revealingRef.current) return
      void request(
        () => api.playAction(hand.id, { expected_actions: hand.action_count, ...choice }),
        'afterHero',
        "Couldn't send your action",
      )
    },
    [api, request],
  )

  const nextHand = useCallback(
    (topUp: boolean) => {
      const current = sessionRef.current
      if (!current || current.hand?.status !== 'complete' || revealingRef.current) return
      void request(
        () => api.nextPlayHand(current.id, { top_up: topUp, expected_hands: current.hands_played }),
        'fromStart',
        "Couldn't deal the next hand",
      )
    },
    [api, request],
  )

  const end = useCallback(() => {
    const current = sessionRef.current
    if (!current) return
    void request(() => api.endPlaySession(current.id), 'whole', "Couldn't end the session")
  }, [api, request])

  let state: PlayState
  if (failure) state = { kind: 'error', message: failure.message, retry }
  else if (!loaded) state = { kind: 'loading' }
  else if (!session) state = { kind: 'idle' }
  else if (session.hand?.status === 'complete' && !revealing) state = { kind: 'handOver' }
  else state = { kind: 'playing' }

  return { state, session, past, shownCount, revealing, busy, start, act, nextHand, end, retry }
}
