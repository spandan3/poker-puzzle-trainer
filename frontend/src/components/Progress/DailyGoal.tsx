import { useId, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { StatsView } from '../../api/types'
import { shortDate } from '../../lib/stats'
import { BarChart } from '../Charts/BarChart'
import styles from './Progress.module.css'

export const GOAL_MIN = 1
export const GOAL_MAX = 500

export interface DailyGoalProps {
  days: StatsView['days']
  /** the goal setting, shown in the box (it can be ahead of `days.goal` until the stats refetch); everything computed shows `days.goal` */
  goal: number
  /** saves the goal; resolves true when it was saved */
  onGoal: (goal: number) => Promise<boolean>
  /** set when the day boundary is UTC because the server doesn't know the browser's zone */
  utcNote?: boolean
}

/** Puzzles per day for two weeks against the goal, and the goal input (commits on Enter or blur). */
export function DailyGoal({ days, goal, onGoal, utcNote = false }: DailyGoalProps) {
  const inputId = useId()
  const titleId = useId()
  const errorId = useId()
  const [draft, setDraft] = useState(String(goal))
  const [seen, setSeen] = useState(goal)
  const [error, setError] = useState<string | null>(null)
  if (seen !== goal) {
    // the goal changed from outside (a save, a refetch): the box follows
    setSeen(goal)
    setDraft(String(goal))
    setError(null)
  }

  const commit = () => {
    const text = draft.trim()
    const n = Number(text)
    if (text === '' || !Number.isInteger(n) || n < GOAL_MIN || n > GOAL_MAX) {
      setError(`Enter a whole number from ${GOAL_MIN} to ${GOAL_MAX}`)
      return
    }
    setError(null)
    if (n === goal) return
    // a failed save reverts the setting, and the box follows it back
    void onGoal(n)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      commit()
    }
  }

  return (
    <section aria-labelledby={titleId} className={styles.section}>
      <h3 id={titleId} className={styles.sectionTitle}>
        Daily goal
      </h3>
      <div className={styles.card}>
        <div className={styles.goalRow}>
          <div className={styles.goalInput}>
            <label htmlFor={inputId}>Puzzles per day</label>
            <input
              id={inputId}
              type="number"
              inputMode="numeric"
              min={GOAL_MIN}
              max={GOAL_MAX}
              step={1}
              className={styles.number}
              value={draft}
              aria-invalid={error !== null || undefined}
              aria-describedby={error !== null ? errorId : undefined}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commit}
              onKeyDown={onKeyDown}
            />
          </div>
          <p className={styles.goalSummary}>
            Today {days.today} / {days.goal} · current streak {days.current_streak} · best{' '}
            {days.best_streak}
          </p>
        </div>
        {error !== null && (
          <p id={errorId} className={styles.fieldError} role="alert">
            {error}
          </p>
        )}
        {utcNote && (
          <p className={styles.hint} data-testid="utc-note">
            Days are counted in UTC (your time zone isn&apos;t known to the server).
          </p>
        )}
        <BarChart
          title="Puzzles per day, last 14 days"
          goal={days.goal}
          width={1120}
          height={240}
          bars={days.recent.map((d) => ({ label: shortDate(d.date), value: d.count }))}
        />
      </div>
    </section>
  )
}
