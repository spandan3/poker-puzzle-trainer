import type { AttemptResult, PuzzleView } from '../../api/types'
import { heroFolded, showdownLine } from '../../lib/result'
import { Card } from '../Card/Card'
import styles from './HandReveal.module.css'

export interface HandRevealProps {
  view: PuzzleView
  result: AttemptResult
}

/**
 * The Hand tab: Villain's cards and profile, the board (the sampled run-out unless Hero folded),
 * the showdown, the "judged on range" note and the simplifications. This is puzzle-specific
 * reveal data, not a Decision component.
 */
export function HandReveal({ view, result }: HandRevealProps) {
  const { reveal, simplifications } = result
  const folded = heroFolded(result)
  const board = folded ? view.board : reveal.runout
  return (
    <div className={styles.hand}>
      <div className={styles.cols}>
        <section className={styles.block}>
          <h3 className={styles.heading}>Villain</h3>
          <div className={styles.cards} role="group" aria-label="Villain's hand">
            {reveal.villain_cards.map((c) => (
              <Card key={c} card={c} size="md" />
            ))}
          </div>
          <p className={styles.profileLine}>
            <span className={styles.profile}>{reveal.profile.label}</span>{' '}
            <span className={styles.muted}>{reveal.profile.description}</span>
          </p>
        </section>

        <section className={styles.block}>
          <h3 className={styles.heading}>{folded ? 'Board' : 'Run-out'}</h3>
          <div
            className={styles.cards}
            role="group"
            aria-label={folded ? 'Board at the decision' : 'Run-out'}
          >
            {board.map((c) => (
              <Card key={c} card={c} size="md" />
            ))}
          </div>
          <p className={styles.showdown}>{showdownLine(result)}</p>
        </section>
      </div>

      <p className={styles.muted}>{result.judged_on_range_note}</p>

      {simplifications.length > 0 && (
        <section className={styles.block}>
          <h3 className={styles.heading}>Simplifications</h3>
          <ul className={styles.list} aria-label="Simplifications">
            {simplifications.map((s) => (
              <li key={s.code}>{s.text}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
