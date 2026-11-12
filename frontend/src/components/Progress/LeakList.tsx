import type { Leak } from '../../api/types'
import { bb1 } from '../../lib/stats'
import styles from './Progress.module.css'

export interface LeakListProps {
  leaks: Leak[]
}

/** The rule-based leaks of the last 200 puzzles; the cost (EV lost in bb) only for the rules that have one. */
export function LeakList({ leaks }: LeakListProps) {
  return (
    <section aria-labelledby="leaks-title" className={styles.section}>
      <h3 id="leaks-title" className={styles.sectionTitle}>
        Leaks
      </h3>
      {leaks.length === 0 ? (
        <p className={styles.card}>No leaks spotted in your last 200 puzzles.</p>
      ) : (
        <ul className={styles.leaks}>
          {leaks.map((leak) => (
            <li key={leak.id} className={styles.leak} data-kind={leak.kind}>
              <div className={styles.leakHead}>
                <h4 className={styles.leakTitle}>{leak.title}</h4>
                {leak.ev_lost_bb !== null && (
                  <span className={styles.cost}>{bb1(leak.ev_lost_bb)} lost</span>
                )}
              </div>
              <p className={styles.leakDetail}>{leak.detail}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
