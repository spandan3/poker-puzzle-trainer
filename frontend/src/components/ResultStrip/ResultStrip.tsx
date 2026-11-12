import { forwardRef } from 'react'
import type { AttemptResult } from '../../api/types'
import {
  guessLines,
  SCORE_LABELS,
  showdownLine,
  VERDICT_LABELS,
  verdictLine,
} from '../../lib/result'
import styles from './ResultStrip.module.css'

export interface ResultStripProps {
  result: AttemptResult
  onNext: () => void
  /** a new puzzle is loading: the Next button shows it and does nothing */
  loading?: boolean
  /** show the `N` key hint and `aria-keyshortcuts` */
  shortcutsOn: boolean
}

/**
 * M5's end of a puzzle, in place of the answer panel: the verdict, EV, guesses vs truth, the
 * revealed profile and "Next puzzle". The verdict is in a live region, so it is announced.
 * M6 replaces this with the full results view.
 */
export const ResultStrip = forwardRef<HTMLButtonElement, ResultStripProps>(function ResultStrip(
  { result, onNext, loading = false, shortcutsOn },
  nextRef,
) {
  const { grade, reveal } = result
  const verdict = VERDICT_LABELS[grade.verdict]
  return (
    <section className={styles.strip} aria-label="Result" data-verdict={grade.verdict}>
      <div className={styles.head} role="status">
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
        <div className={styles.fact}>
          <dt>Villain</dt>
          <dd>
            <span className={styles.profile}>{reveal.profile.label}</span>{' '}
            <span className={styles.muted}>{reveal.profile.description}</span>
          </dd>
        </div>
        <div className={styles.fact}>
          <dt>Run-out</dt>
          <dd>{showdownLine(result)}</dd>
        </div>
      </dl>

      {grade.intent_flag && <p className={styles.note}>{grade.intent_flag}</p>}

      <div className={styles.foot}>
        <p className={styles.muted}>{result.judged_on_range_note}</p>
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
})
