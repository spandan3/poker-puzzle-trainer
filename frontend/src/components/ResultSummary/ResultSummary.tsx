import { forwardRef } from 'react'
import type { AttemptResult } from '../../api/types'
import { guessLines, heroFolded, SCORE_LABELS, VERDICT_LABELS, verdictLine } from '../../lib/result'
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
          <span className={styles.line}>{verdictLine(result)}</span>
        </div>

        <dl className={styles.facts}>
          {guessLines(result).map((g) => (
            <div key={g.label} className={styles.fact}>
              <dt>{g.label}</dt>
              <dd>
                you {g.guess} · actual {g.actual}
                {g.score && (
                  <span className={styles.score} data-score={g.score}>
                    {SCORE_LABELS[g.score]}
                  </span>
                )}
              </dd>
            </div>
          ))}
        </dl>

        {grade.intent_flag && <p className={styles.note}>{grade.intent_flag}</p>}

        <div className={styles.foot}>
          {/* after a fold the run-out note would contradict the fold screen */}
          {!heroFolded(result) && <p className={styles.muted}>{result.judged_on_range_note}</p>}
          <button type="button" className={styles.details} onClick={onDetails}>
            Details
          </button>
          <button
            ref={nextRef}
            type="button"
            className={styles.next}
            onClick={() => {
              if (!loading) onNext()
            }}
            aria-disabled={loading || undefined}
            aria-keyshortcuts={shortcutsOn ? 'N' : undefined}
            data-shortcut={shortcutsOn ? 'next' : undefined}
          >
            {loading ? 'Dealing…' : 'Next puzzle'}
            {shortcutsOn && (
              <kbd className={styles.kbd} aria-hidden="true">
                N
              </kbd>
            )}
          </button>
        </div>
      </section>
    )
  },
)
