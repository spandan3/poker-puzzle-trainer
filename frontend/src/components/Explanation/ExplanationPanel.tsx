import type { Explanation } from '../../api/types'
import styles from './ExplanationPanel.module.css'

export interface ExplanationPanelProps {
  explanation: Explanation
  /** The local model's name while its rewrite is on the way: shows a status line. */
  pendingModel?: string | null
  /** The settings' LLM status: tells the footer why a template is shown. */
  llmStatus?: 'off' | 'ready' | 'unavailable' | null
  /** The settings' reason for `unavailable`. */
  llmDetail?: string | null
  /** The request for the rewrite failed. */
  requestFailed?: boolean
}

const unavailableNote = (detail: string | null | undefined) =>
  detail ? `The local model isn't available: ${detail}.` : "The local model isn't available."

/** The footer's one line: where the text comes from, or why it is the trainer's own. */
function footerText(p: ExplanationPanelProps): string {
  const { explanation: e } = p
  if (e.source === 'llm') {
    return `Reworded by ${e.model ?? 'the local model'}, a local model. Every number in it was checked against the grader's numbers.`
  }
  const off =
    'Explanations come from templates. A local model (Ollama) can reword them: see backend/.env.example.'
  switch (e.fallback) {
    case 'guardrail':
      return "The local model's text used a number the grader didn't compute, so the trainer's own text is shown."
    case 'timeout':
      return "The local model didn't answer in time."
    case 'unavailable':
      return unavailableNote(p.llmDetail)
    case 'error':
    case 'invalid':
      return "The local model's answer couldn't be used, so the trainer's own text is shown."
    case 'off':
      return off
  }
  if (p.requestFailed)
    return "The local model couldn't be reached, so the trainer's own text is shown."
  if (p.llmStatus === 'off') return off
  if (p.llmStatus === 'unavailable') return unavailableNote(p.llmDetail)
  return 'Written by the trainer from the graded numbers.'
}

/** Suits as text glyphs: drop an emoji selector (U+FE0F) and ask for text style (U+FE0E). */
const textSuits = (s: string) => s.replace(/([♠♣♥♦])\uFE0F?/g, '$1\uFE0E')

/** The Why tab: the headline, then each section as a titled run of paragraphs. Plain text only. */
export function ExplanationPanel(props: ExplanationPanelProps) {
  const { explanation, pendingModel } = props
  return (
    <div className={styles.panel}>
      {pendingModel != null && (
        <p className={styles.pending} role="status">
          Rewriting in plain English with {pendingModel}…
        </p>
      )}
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
      <p className={styles.footer}>{footerText(props)}</p>
    </div>
  )
}
