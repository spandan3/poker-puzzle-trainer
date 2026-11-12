import type { Explanation } from '../../api/types'
import styles from './ExplanationPanel.module.css'

export interface ExplanationPanelProps {
  explanation: Explanation
}

/** Suits as text glyphs: drop an emoji selector (U+FE0F) and ask for text style (U+FE0E). */
const textSuits = (s: string) => s.replace(/([♠♣♥♦])\uFE0F?/g, '$1\uFE0E')

/** The Why tab: the headline, then each section as a titled run of paragraphs. Plain text only. */
export function ExplanationPanel({ explanation }: ExplanationPanelProps) {
  return (
    <div className={styles.panel}>
      <p className={styles.headline}>{textSuits(explanation.headline)}</p>
      {explanation.sections.map((section) => (
        <section key={section.id} className={styles.section}>
          <h3 className={styles.title}>{section.title}</h3>
          {section.paragraphs.map((text, i) => (
            <p key={i} className={styles.paragraph}>
              {textSuits(text)}
            </p>
          ))}
        </section>
      ))}
      <p className={styles.footer}>Written by the trainer from the graded numbers.</p>
    </div>
  )
}
