import type { StatsView } from '../../api/types'
import { formatEvBb } from '../../lib/format'
import { deltaText, pct, plural, pts, rollingWindowOf } from '../../lib/stats'
import styles from './Progress.module.css'

export interface StatTilesProps {
  stats: StatsView
}

interface Tile {
  id: string
  label: string
  value: string
  note: string | null
  /** a tone for the note (the change against the window before) */
  tone?: 'good' | 'bad' | 'neutral'
}

// The headline values are averaged over the API's `rolling_window` (the `*_last50` names are only
// names): every note takes the window from there, as the trend charts do.
function tiles({ headline, streak, days, rolling_window }: StatsView): Tile[] {
  const n = rollingWindowOf(rolling_window)
  const last = n === null ? 'recent' : `last ${n}`
  const ev = headline.ev_lost_bb_last50
  const prev = headline.ev_lost_bb_prev50
  const delta = deltaText(ev, prev, n)
  return [
    {
      id: 'ev',
      label: 'EV lost per decision',
      value: ev === null ? '—' : formatEvBb(ev),
      note: delta?.text ?? `${last} puzzles`,
      // the same rounded difference as the text: "same as the N before" is never coloured
      tone: delta?.tone,
    },
    {
      id: 'accuracy',
      label: 'Accuracy',
      value: headline.accuracy_last50 === null ? '—' : pct(headline.accuracy_last50),
      note: `Best or Fine, ${last}`,
    },
    {
      id: 'equity',
      label: 'Equity error',
      value: headline.equity_error_last50 === null ? '—' : pts(headline.equity_error_last50),
      note: `average, ${last}`,
    },
    {
      id: 'range',
      label: 'Range-read error',
      value:
        headline.range_read_error_last50 === null ? '—' : pts(headline.range_read_error_last50),
      note: headline.range_read_error_last50 === null ? 'no range reads yet' : `average, ${last}`,
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

/** The totals line and a row of headline tiles (the last `rolling_window` first attempts unless noted). */
export function StatTiles({ stats }: StatTilesProps) {
  return (
    <section aria-labelledby="summary-title" className={styles.summary}>
      <h3 id="summary-title" className={styles.srOnly}>
        Summary
      </h3>
      <p className={styles.totals} data-testid="progress-totals">
        {plural(stats.totals.first_attempts, 'puzzle')} answered ·{' '}
        {plural(stats.totals.retries, 'practice attempt')}
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
