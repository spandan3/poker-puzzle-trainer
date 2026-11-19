import { forwardRef } from 'react'
import type { AttemptResult } from '../../api/types'
import { nowrapUnits } from '../../lib/format'
import {
  guessLines,
  guessText,
  heroFolded,
  judgedNote,
  SCORE_LABELS,
  VERDICT_LABELS,
  verdictLine,
} from '../../lib/result'
import { Badge, Button } from '../ui'
import styles from './ResultSummary.module.css'

export interface ResultSummaryProps {
  result: AttemptResult
  onNext: () => void
  /** a new puzzle is loading: the Next button shows it and does nothing */
  loading?: boolean
  /** show the `N` key hint and `aria-keyshortcuts` */
  shortcutsOn: boolean
  /** scroll to the details (Why / Options / Maths / Range / Hand) and focus their tabs */
  onDetails: () => void
}

/**
 * The end of a puzzle, in place of the answer panel: the verdict, guesses vs truth, "Details" and "Next puzzle". The working is in `DecisionDetails` below.
 */
export const ResultSummary = forwardRef<HTMLButtonElement, ResultSummaryProps>(
  function ResultSummary({ result, onNext, loading = false, shortcutsOn, onDetails }, nextRef) {
    const { grade } = result
    const verdict = VERDICT_LABELS[grade.verdict]
    return (
      <section className={styles.strip} aria-label="Result" data-verdict={grade.verdict}>
        {/* announced by the app's live region (mounted before the result), not from here */}
        <div className={styles.head}>
          <span className={styles.verdict} data-verdict={grade.verdict}>
            {verdict}
          </span>
          <span className={styles.line}>{nowrapUnits(verdictLine(result))}</span>
        </div>

        <dl className={styles.facts}>
          {guessLines(result).map((g) => (
            <div key={g.label} className={styles.fact}>
              <dt>{g.label}</dt>
              <dd>
                {guessText(g)}
                {g.score && (
                  // neutral: verdict colours are for the decision, not for the estimate
                  <span className={styles.score} data-score={g.score}>
                    <Badge tone="neutral" title={g.scoreTitle}>
                      {SCORE_LABELS[g.score]}
                    </Badge>
                  </span>
                )}
              </dd>
            </div>
          ))}
        </dl>

        {grade.intent_flag && <p className={styles.note}>{grade.intent_flag}</p>}

        <div className={styles.foot}>
          <p className={styles.muted}>
            {judgedNote(result.judged_on_range_note, heroFolded(result))}
          </p>
          <Button variant="secondary" onClick={onDetails}>
            Details
          </Button>
          <Button
            ref={nextRef}
            variant="primary"
            kbd={shortcutsOn ? 'N' : undefined}
            busy={loading}
            // the page's primary target (App focuses it after a navigation to Puzzles)
            data-primary-focus=""
            onClick={() => onNext()}
            aria-keyshortcuts={shortcutsOn ? 'N' : undefined}
            data-shortcut={shortcutsOn ? 'next' : undefined}
          >
            {loading ? 'Dealing…' : 'Next puzzle'}
          </Button>
        </div>
      </section>
    )
  },
)
