import type { ReactNode } from 'react'
import styles from './ui.module.css'

export type BadgeTone = 'best' | 'fine' | 'mistake' | 'blunder' | 'neutral' | 'profile'

/** A pill for a verdict, a label or the Villain's profile. */
export function Badge({ tone = 'neutral', children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span className={styles.badge} data-tone={tone}>
      {children}
    </span>
  )
}
