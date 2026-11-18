import type { ReactNode } from 'react'
import styles from './ui.module.css'

export type BadgeTone = 'best' | 'fine' | 'mistake' | 'blunder' | 'neutral' | 'profile'

/** A pill for a verdict, a label or the Villain's profile. */
export function Badge({
  tone = 'neutral',
  title,
  children,
}: {
  tone?: BadgeTone
  /** a tooltip that says what the badge rates */
  title?: string
  children: ReactNode
}) {
  return (
    <span className={styles.badge} data-tone={tone} title={title}>
      {children}
    </span>
  )
}
