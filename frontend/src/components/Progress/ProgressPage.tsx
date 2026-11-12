import { useCallback, useEffect, useRef, useState } from 'react'
import type * as client from '../../api/client'
import { ApiError } from '../../api/client'
import type { StatsView } from '../../api/types'
import type { Page } from '../../lib/page'
import { isPlainLeftClick, pathOf } from '../../lib/page'
import { localTimeZone } from '../../lib/stats'
import { Breakdowns } from './Breakdowns'
import { DailyGoal } from './DailyGoal'
import { LeakList } from './LeakList'
import { StatTiles } from './StatTiles'
import { TrendCharts } from './TrendCharts'
import styles from './Progress.module.css'

/** The parts of the API client the Progress page uses (injectable for tests). */
export type ProgressApi = Pick<typeof client, 'getStats' | 'getHistory'>

export interface ProgressPageProps {
  api: ProgressApi
  /** the daily goal setting (`null` until the settings arrive: the stats' own goal shows) */
  goal: number | null
  /** saves the goal; resolves true when saved (the stats are then fetched again) */
  onGoal: (goal: number) => Promise<boolean>
  /** a plain click on "Start a puzzle" goes here; without it the link is a normal navigation */
  onNavigate?: (page: Page) => void
}

type Load =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; stats: StatsView; utcNote: boolean }

/** The stats for the browser's zone; a 422 (the server doesn't know the zone) retries once with UTC. */
async function fetchStats(api: ProgressApi): Promise<{ stats: StatsView; utcNote: boolean }> {
  const tz = localTimeZone()
  try {
    return { stats: await api.getStats(tz), utcNote: false }
  } catch (error) {
    if (error instanceof ApiError && error.status === 422 && tz !== 'UTC') {
      return { stats: await api.getStats('UTC'), utcNote: true }
    }
    throw error
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 0) {
    return "Can't reach the server. Check it is running, then retry."
  }
  return "Couldn't load your progress."
}

export function ProgressPage({ api, goal, onGoal, onNavigate }: ProgressPageProps) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' })
  const seq = useRef(0)

  // `silent`: keep showing the page while the stats are fetched again (after a goal save)
  const fetchNow = useCallback(
    (silent: boolean) => {
      const mine = ++seq.current
      if (!silent) setLoad({ kind: 'loading' })
      fetchStats(api).then(
        ({ stats, utcNote }) => {
          if (mine === seq.current) setLoad({ kind: 'ready', stats, utcNote })
        },
        (error: unknown) => {
          if (mine !== seq.current) return
          // a failed silent refresh keeps the page we have
          setLoad((now) =>
            silent && now.kind === 'ready' ? now : { kind: 'error', message: errorMessage(error) },
          )
        },
      )
    },
    [api],
  )

  // Once: the flag is never reset and the request never aborted, so StrictMode's double effect
  // sends one request.
  const started = useRef(false)
  useEffect(() => {
    if (started.current) return
    started.current = true
    fetchNow(false)
  }, [fetchNow])

  // The stats count days against their own goal; when the setting differs (it was changed
  // elsewhere, or the stats are older), fetch again once per goal value so the page shows one goal.
  const refetchedFor = useRef<number | null>(null)
  const statsGoal = load.kind === 'ready' ? load.stats.days.goal : null
  useEffect(() => {
    if (statsGoal === null || goal === null || goal === statsGoal) return
    if (refetchedFor.current === goal) return
    refetchedFor.current = goal
    fetchNow(true)
  }, [goal, statsGoal, fetchNow])

  const saveGoal = async (next: number): Promise<boolean> => {
    // the setting changes at once (optimistic): the stats are fetched when the save succeeds,
    // not for the unsaved value
    refetchedFor.current = next
    const saved = await onGoal(next)
    if (saved) fetchNow(true)
    return saved
  }

  return (
    <div className={styles.page} data-testid="progress-page">
      <h2 className={styles.pageTitle}>Progress</h2>
      {load.kind === 'loading' && (
        <p className={styles.status} role="status">
          Loading your progress…
        </p>
      )}
      {load.kind === 'error' && (
        <div className={styles.status} role="alert">
          <span>{load.message}</span>{' '}
          <button type="button" className={styles.button} onClick={() => fetchNow(false)}>
            Retry
          </button>
        </div>
      )}
      {load.kind === 'ready' &&
        (load.stats.totals.first_attempts === 0 ? (
          <div className={styles.empty}>
            <p className={styles.emptyTitle}>No puzzles answered yet</p>
            <p className={styles.hint}>
              Your trends, breakdowns and leaks appear here once you have answered some puzzles.
            </p>
            <a
              href={pathOf('puzzles')}
              className={styles.link}
              onClick={(e) => {
                if (onNavigate && isPlainLeftClick(e)) {
                  e.preventDefault()
                  onNavigate('puzzles')
                }
              }}
            >
              Start a puzzle
            </a>
          </div>
        ) : (
          <>
            <StatTiles stats={load.stats} />
            <TrendCharts trend={load.stats.trend} />
            <DailyGoal
              days={load.stats.days}
              goal={goal ?? load.stats.days.goal}
              onGoal={saveGoal}
              utcNote={load.utcNote}
            />
            <LeakList leaks={load.stats.leaks} />
            <Breakdowns breakdowns={load.stats.breakdowns} />
            {/* Task 5: the history table (filters, paging, Replay and Result buttons) goes here,
                taking `api.getHistory`. */}
            <section aria-label="History" data-testid="history-slot" />
          </>
        ))}
    </div>
  )
}
