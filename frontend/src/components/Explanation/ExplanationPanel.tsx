import type { Explanation } from '../../api/types'
import styles from './ExplanationPanel.module.css'

export interface ExplanationPanelProps {
  explanation: Explanation
}

/** The Why tab: the headline, then each section as a titled run of paragraphs. Plain text only. */
export function ExplanationPanel({ explanation }: ExplanationPanelProps) {
  return (
    <div className={styles.panel}>
      <p className={styles.headline}>{explanation.headline}</p>
      {explanation.sections.map((section) => (
        <section key={section.id} className={styles.section}>
          <h3 className={styles.title}>{section.title}</h3>
          {section.paragraphs.map((text, i) => (
            <p key={i} className={styles.paragraph}>
              {text}
            </p>
          ))}
        </section>
      ))}
      <p className={styles.footer}>Written by the trainer from the graded numbers.</p>
    </div>
  )
}
