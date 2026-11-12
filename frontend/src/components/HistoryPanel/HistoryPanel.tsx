import { useId } from 'react'
import type { ActionLogEntry, PuzzleView } from '../../api/types'
import { groupHistory, STREET_LABELS } from '../../lib/history'
import { Card } from '../Card/Card'
import styles from './HistoryPanel.module.css'

export interface HistoryPanelProps {
  view: PuzzleView
  /** Hero's submitted action: shown in place of "Hero to act" once the puzzle is answered. */
  answer?: ActionLogEntry
  className?: string
}

/** The hand so far, street by street, ending with "Hero to act". */
export function HistoryPanel({ view, answer, className }: HistoryPanelProps) {
  const base = useId()
  const sections = groupHistory(view, answer)
  return (
    <aside
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
                    <span className={styles.text}>{item.text}</span>
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
                <span className={styles.text}>{section.answer.text}</span>
                <span className={styles.yours}>your answer</span>
              </p>
            )}
            {section.toAct === 'hero' && (
              <p className={styles.toAct}>
                <span className={styles.toActDot} aria-hidden="true" />
                Hero to act
              </p>
            )}
          </section>
        )
      })}
    </aside>
  )
}
