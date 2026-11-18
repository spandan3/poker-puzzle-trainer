import { useId } from 'react'
import type { ReactNode } from 'react'
import styles from './ui.module.css'

export interface PanelProps {
  title?: string
  /** The heading level of `title`, set by the page's outline (default 3). */
  headingLevel?: 2 | 3 | 4
  /** Controls at the right of the title. */
  actions?: ReactNode
  /** No padding, for tables that run edge to edge. */
  flush?: boolean
  className?: string
  children: ReactNode
}

/** The card surface. Panels are never nested: an inner region uses a divider instead. */
export function Panel({
  title,
  headingLevel = 3,
  actions,
  flush = false,
  className,
  children,
}: PanelProps) {
  const titleId = useId()
  const Heading = `h${headingLevel}` as const
  return (
    <section
      className={[styles.panel, className].filter(Boolean).join(' ')}
      aria-labelledby={title ? titleId : undefined}
      data-flush={flush ? '' : undefined}
    >
      {(title || actions) && (
        <header className={styles.panelHeader}>
          {title && (
            <Heading id={titleId} className={styles.panelTitle}>
              {title}
            </Heading>
          )}
          {actions && <div className={styles.panelActions}>{actions}</div>}
        </header>
      )}
      <div className={styles.panelBody}>{children}</div>
    </section>
  )
}
