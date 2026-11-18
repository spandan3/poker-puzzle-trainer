import { useId } from 'react'
import type { StatsView } from '../../api/types'
import type { Page } from '../../lib/page'
import { isPlainLeftClick, pathOf } from '../../lib/page'
import { shortDate } from '../../lib/stats'
import { BarChart } from '../Charts/BarChart'
import styles from './Progress.module.css'

export interface DailyGoalProps {
  days: StatsView['days']
  /** a plain click on the Settings link goes here; without it the link is a normal navigation */
  onNavigate?: (page: Page) => void
  /** set when the day boundary is UTC because the server doesn't know the browser's zone */
  utcNote?: boolean
}

/** Puzzles per day for two weeks against the goal. The goal itself is set on the Settings page. */
export function DailyGoal({ days, onNavigate, utcNote = false }: DailyGoalProps) {
  const titleId = useId()
  return (
    <section aria-labelledby={titleId} className={styles.section}>
      <h3 id={titleId} className={styles.sectionTitle}>
        Daily goal
      </h3>
      <div className={styles.card}>
        <div className={styles.goalRow}>
          <p className={styles.goalSummary}>
            Goal: {days.goal} a day ·{' '}
            <a
              href={pathOf('settings')}
              className={styles.textLink}
              onClick={(e) => {
                if (onNavigate && isPlainLeftClick(e)) {
                  e.preventDefault()
                  onNavigate('settings')
                }
              }}
            >
              Change in Settings
            </a>
          </p>
          <p className={styles.goalSummary}>
            Today {days.today} / {days.goal} · current streak {days.current_streak} · best{' '}
            {days.best_streak}
          </p>
        </div>
        {utcNote && (
          <p className={styles.hint} data-testid="utc-note">
            Days are counted in UTC (your time zone isn&apos;t known to the server).
          </p>
        )}
        <BarChart
          title="Puzzles per day, last 14 days"
          goal={days.goal}
          width={900}
          height={240}
          bars={days.recent.map((d) => ({ label: shortDate(d.date), value: d.count }))}
        />
      </div>
    </section>
  )
}
