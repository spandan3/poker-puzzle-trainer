import type { Ref } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type * as client from '../../api/client'
import { ApiError } from '../../api/client'
import type { StatsView } from '../../api/types'
import type { Page } from '../../lib/page'
import { isPlainLeftClick, pathOf } from '../../lib/page'
import { localTimeZone } from '../../lib/stats'
import { Button } from '../ui'
import { Breakdowns } from './Breakdowns'
import { DailyGoal } from './DailyGoal'
import { HistoryTable } from './HistoryTable'
import type { HistoryApi } from './HistoryTable'
import { LeakList } from './LeakList'
import { StatTiles } from './StatTiles'
import { TrendCharts } from './TrendCharts'
import styles from './Progress.module.css'

/** The parts of the API client the Progress page uses (injectable for tests). */
export type ProgressApi = Pick<typeof client, 'getStats'> & HistoryApi

export interface ProgressPageProps {
  api: ProgressApi
  /** a plain click on "Start a puzzle" or "Change in Settings" goes here; without it the link is a normal navigation */
  onNavigate?: (page: Page) => void
  /** Villain profiles from the settings (`null` until they arrive: the stats' own list shows) */
  profiles?: { name: string; label: string }[] | null
  /** the page heading, so the app can focus it after a page switch */
  titleRef?: Ref<HTMLHeadingElement>
  /** "Replay" on a history row: answer that puzzle again (the app switches to Puzzles) */
  onReplay: (puzzleId: number) => void
  /** "Result" on a history row: reopen that attempt's stored result */
  onResult: (attemptId: number) => void
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

export function ProgressPage({
  api,
  onNavigate,
  profiles = null,
  titleRef,
  onReplay,
  onResult,
}: ProgressPageProps) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' })
  const seq = useRef(0)

  const fetchNow = useCallback(() => {
    const mine = ++seq.current
    setLoad({ kind: 'loading' })
    fetchStats(api).then(
      ({ stats, utcNote }) => {
        if (mine === seq.current) setLoad({ kind: 'ready', stats, utcNote })
      },
      (error: unknown) => {
        if (mine === seq.current) setLoad({ kind: 'error', message: errorMessage(error) })
      },
    )
  }, [api])

  // Once: the flag is never reset and the request never aborted, so StrictMode's double effect
  // sends one request.
  const started = useRef(false)
  useEffect(() => {
    if (started.current) return
    started.current = true
    fetchNow()
  }, [fetchNow])

  return (
    <div className={styles.page} data-testid="progress-page">
      <h2 className={styles.pageTitle} ref={titleRef} tabIndex={-1}>
        Progress
      </h2>
      {load.kind === 'loading' && (
        <p className={styles.status} role="status">
          Loading your progress…
        </p>
      )}
      {load.kind === 'error' && (
        <div className={styles.status} role="alert">
          <span>{load.message}</span>{' '}
          <Button size="sm" onClick={fetchNow}>
            Retry
          </Button>
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
            <TrendCharts trend={load.stats.trend} rollingWindow={load.stats.rolling_window} />
            <DailyGoal days={load.stats.days} onNavigate={onNavigate} utcNote={load.utcNote} />
            <LeakList leaks={load.stats.leaks} />
            <Breakdowns breakdowns={load.stats.breakdowns} />
            <HistoryTable
              api={api}
              // every profile, played or not; the stats' own list when the settings aren't loaded
              profiles={
                profiles !== null
                  ? profiles.map((p) => ({ key: p.name, label: p.label }))
                  : load.stats.breakdowns.profile.map((r) => ({ key: r.key, label: r.label }))
              }
              onReplay={onReplay}
              onResult={onResult}
            />
          </>
        ))}
    </div>
  )
}
