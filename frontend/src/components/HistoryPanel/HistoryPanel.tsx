import { useEffect, useId, useRef } from 'react'
import type { ActionLogEntry, TableView } from '../../api/types'
import { nowrapUnits } from '../../lib/format'
import { groupHistory, STREET_LABELS } from '../../lib/history'
import { Card } from '../Card/Card'
import styles from './HistoryPanel.module.css'

export interface HistoryPanelProps {
  view: TableView
  /** Hero's submitted action: shown in place of "Hero to act" once the puzzle is answered. */
  answer?: ActionLogEntry
  /** Who the last street waits for (default Hero); `null` once the hand is over. */
  toAct?: 'hero' | 'villain' | null
  /** A new value (the puzzle's id) scrolls the panel back to the end, whatever else is equal. */
  resetKey?: string | number
  className?: string
}

/**
 * The hand so far, street by street, ending with "Hero to act". `view` is any table: a puzzle's,
 * Play's current hand (cut to what the reveal has shown) or, beside a Play analysis, the
 * `review.view` of the step picked (the hand up to that decision, with `toAct` "hero").
 */
export function HistoryPanel({ view, answer, toAct, resetKey, className }: HistoryPanelProps) {
  const base = useId()
  const sections = groupHistory(view, answer, toAct)
  const panelRef = useRef<HTMLElement>(null)
  const answered = answer !== undefined
  // A long history scrolls inside the panel (the table screens give it a fixed height). Start at
  // the end, so the latest action and who acts next are on show; the heading scrolls away.
  useEffect(() => {
    const panel = panelRef.current
    if (panel && panel.scrollHeight > panel.clientHeight) panel.scrollTop = panel.scrollHeight
  }, [resetKey, view.history.length, view.street, answered, toAct])
  return (
    <aside
      ref={panelRef}
      className={[styles.panel, className].filter(Boolean).join(' ')}
      aria-labelledby={`${base}-title`}
    >
      <h2 id={`${base}-title`} className={styles.title}>
        Action
      </h2>
      {sections.map((section) => {
        const label = STREET_LABELS[section.street]
        const headingId = `${base}-${section.street}`
        return (
          <section
            key={section.street}
            className={styles.street}
            aria-labelledby={headingId}
            data-street={section.street}
          >
            <div className={styles.streetHead}>
              <h3 id={headingId} className={styles.streetName}>
                {label}
              </h3>
              {section.board.length > 0 && (
                <span className={styles.board}>
                  {section.board.map((card) => (
                    <Card key={card} card={card} size="sm" className={styles.card} />
                  ))}
                </span>
              )}
            </div>
            {section.entries.length > 0 ? (
              <ol className={styles.list} aria-label={`${label} actions`}>
                {section.entries.map((item, i) => (
                  <li key={i} className={styles.entry} data-actor={item.actor}>
                    <span className={styles.who}>
                      <span className={styles.dot} aria-hidden="true" />
                      <span className={styles.name}>
                        {item.actor === 'hero' ? 'Hero' : 'Villain'}
                      </span>
                      <span className={styles.position}>{item.position}</span>
                    </span>
                    <span className={styles.text}>{nowrapUnits(item.text)}</span>
                  </li>
                ))}
              </ol>
            ) : (
              !section.answer && <p className={styles.none}>No action yet</p>
            )}
            {section.answer && (
              <p className={styles.answer} data-actor="hero">
                <span className={styles.who}>
                  <span className={styles.dot} aria-hidden="true" />
                  <span className={styles.name}>Hero</span>
                  <span className={styles.position}>{section.answer.position}</span>
                </span>
                <span className={styles.text}>{nowrapUnits(section.answer.text)}</span>
                <span className={styles.yours}>your answer</span>
              </p>
            )}
            {section.toAct && (
              <p className={styles.toAct}>
                <span className={styles.toActDot} aria-hidden="true" />
                {section.toAct === 'hero' ? 'Hero' : 'Villain'} to act
              </p>
            )}
          </section>
        )
      })}
    </aside>
  )
}
