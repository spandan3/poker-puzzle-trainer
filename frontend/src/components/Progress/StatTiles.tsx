import type { StatsView } from '../../api/types'
import { formatEvBb } from '../../lib/format'
import { deltaText, pct, pts } from '../../lib/stats'
import styles from './Progress.module.css'

export interface StatTilesProps {
  stats: StatsView
}

interface Tile {
  id: string
  label: string
  value: string
  note: string | null
  /** a tone for the note (the change against the 50 before) */
  tone?: 'good' | 'bad'
}

function tiles({ headline, streak, days }: StatsView): Tile[] {
  const ev = headline.ev_lost_bb_last50
  const prev = headline.ev_lost_bb_prev50
  const delta = deltaText(ev, prev)
  return [
    {
      id: 'ev',
      label: 'EV lost per decision',
      value: ev === null ? '—' : formatEvBb(ev),
      note: delta ?? 'last 50 puzzles',
      tone:
        delta === null || ev === null || prev === null
          ? undefined
          : ev < prev
            ? 'good'
            : ev > prev
              ? 'bad'
              : undefined,
    },
    {
      id: 'accuracy',
      label: 'Accuracy',
      value: headline.accuracy_last50 === null ? '—' : pct(headline.accuracy_last50),
      note: 'Best or Fine, last 50',
    },
    {
      id: 'equity',
      label: 'Equity error',
      value: headline.equity_error_last50 === null ? '—' : pts(headline.equity_error_last50),
      note: 'average, last 50',
    },
    {
      id: 'range',
      label: 'Range-read error',
      value:
        headline.range_read_error_last50 === null ? '—' : pts(headline.range_read_error_last50),
      note: 'average, last 50',
    },
    {
      id: 'streak',
      label: 'Streak',
      value: String(streak.current),
      note: `best ${streak.best}`,
    },
    {
      id: 'today',
      label: 'Today',
      value: `${days.today} / ${days.goal}`,
      note: `${days.current_streak}-day streak`,
    },
  ]
}

/** The totals line and a row of headline tiles (last 50 first attempts unless noted). */
export function StatTiles({ stats }: StatTilesProps) {
  return (
    <section aria-label="Summary" className={styles.summary}>
      <p className={styles.totals} data-testid="progress-totals">
        {stats.totals.first_attempts} puzzles answered · {stats.totals.retries} practice attempts
      </p>
      <ul className={styles.tiles}>
        {tiles(stats).map((t) => (
          <li key={t.id} className={styles.tile} data-testid={`tile-${t.id}`}>
            <span className={styles.tileLabel}>{t.label}</span>
            <span className={styles.tileValue}>{t.value}</span>
            {t.note !== null && (
              <span className={styles.tileNote} data-tone={t.tone}>
                {t.note}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
