import type { CSSProperties, ReactNode } from 'react'
import { DecisionDetails } from '../../components/Decision/DecisionDetails'
import { ExplanationPanel } from '../../components/Explanation/ExplanationPanel'
import { ResultSummary } from '../../components/ResultSummary/ResultSummary'
import { decisionFromAttempt } from '../../lib/decision'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
import { neverContinuesAttempt } from '../../test/synthetic'
import type { GalleryEntry } from '../Gallery'

const caption: CSSProperties = {
  margin: 'var(--space-5) 0 var(--space-2)',
  color: 'var(--color-text-muted)',
  fontSize: 'var(--text-sm)',
}

function Demo({ title, children }: { title: string; children: ReactNode }) {
  return (
    <figure style={{ margin: 'var(--space-6) 0 0' }}>
      <figcaption style={caption}>{title}</figcaption>
      <div style={{ display: 'grid', gap: 'var(--space-3)' }}>{children}</div>
    </figure>
  )
}

// every attempt fixture with the puzzle it was made on
const cases = [
  { title: 'Flop, bet 33% (best)', puzzle: 'flop_unopened', attempt: attemptFixture('bet') },
  {
    title: 'Flop facing a raise, fold (mistake)',
    puzzle: 'facing_postflop_raise',
    attempt: attemptFixture('fold'),
  },
  {
    title: 'Flop facing a raise, call (best)',
    puzzle: 'facing_postflop_raise',
    attempt: attemptFixture('call'),
  },
  {
    title: 'Pre-flop, raise',
    puzzle: 'preflop_bb_facing_open',
    attempt: attemptFixture('raise_preflop'),
  },
  {
    title: 'Pre-flop, fold',
    puzzle: 'preflop_btn_first_in',
    attempt: attemptFixture('fold_preflop'),
  },
  { title: 'River, check', puzzle: 'river', attempt: attemptFixture('check_river') },
  {
    title: 'Flop, custom size',
    puzzle: 'custom_allowed',
    attempt: attemptFixture('custom'),
  },
  {
    title: 'Flop, Villain never continues (synthetic, derived from the bet fixture)',
    puzzle: 'flop_unopened',
    attempt: neverContinuesAttempt(),
  },
]

const entry: GalleryEntry = {
  title: 'Results',
  render: () => (
    <div>
      {cases.map(({ title, puzzle, attempt }) => {
        const view = puzzleFixture(puzzle)
        return (
          <Demo key={title} title={title}>
            <ResultSummary result={attempt} onNext={() => {}} onDetails={() => {}} shortcutsOn />
            <DecisionDetails
              decision={decisionFromAttempt(view, attempt)}
              whyTab={<ExplanationPanel explanation={attempt.explanation} />}
            />
          </Demo>
        )
      })}
    </div>
  ),
}

export default entry
