import type { PlaySessionSummary } from '../../api/types'
import { signedBb } from '../../lib/play'
import styles from './Play.module.css'

export const HELP_NOTE =
  'Pre-flop, the bot responds the same way to a 2.5x and a 3x open or 3-bet, and treats an all-in as a jam. There is no limping and no small 4-bet.'

export interface StartPanelProps {
  onStart: () => void
  /** a request is in flight */
  busy: boolean
  /** past sessions, newest first (null: not loaded yet) */
  past: PlaySessionSummary[] | null
}

function dateText(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Shown when there is no open session: start one, see the old ones, read what the bot does. */
export function StartPanel({ onStart, busy, past }: StartPanelProps) {
  return (
    <section className={styles.start} aria-label="Start a session">
      <h2 className={styles.startTitle}>Play against a bot</h2>
      <p className={styles.startText}>
        A heads-up cash game, 100 bb deep, against one bot with a random profile. Play full hands,
        then analyse any hand afterwards.
      </p>
      <button type="button" className={styles.primary} disabled={busy} onClick={onStart}>
        Start session
      </button>

      {past !== null && past.length > 0 && (
        <div className={styles.past}>
          <h3 className={styles.pastTitle}>Past sessions</h3>
          <ul className={styles.pastList} aria-label="Past sessions">
            {past.map((s) => (
              <li key={s.id} className={styles.pastItem}>
                <span className={styles.pastNet}>{signedBb(Math.round(s.net_bb * 2))}</span>
                <span>
                  {s.hands_played} {s.hands_played === 1 ? 'hand' : 'hands'}
                </span>
                <span>vs {s.profile_label}</span>
                <span className={styles.pastDate}>{dateText(s.created_at)}</span>
                {s.open && <span className={styles.pastOpen}>open</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className={styles.note}>{HELP_NOTE}</p>
    </section>
  )
}
