import type { CSSProperties } from 'react'
import type { AttemptResult } from '../../api/types'
import { RangePanel } from '../../components/Decision/RangePanel'
import { decisionFromAttempt } from '../../lib/decision'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
import { neverContinuesAttempt } from '../../test/synthetic'
import type { GalleryEntry } from '../Gallery'

const caption: CSSProperties = {
  margin: 'var(--space-5) 0 var(--space-2)',
  color: 'var(--color-text-muted)',
  fontSize: 'var(--text-sm)',
}

const box: CSSProperties = {
  padding: 'var(--space-3) var(--space-4) var(--space-4)',
  background: 'var(--color-panel)',
  border: '1px solid var(--color-panel-border)',
  borderRadius: 'var(--radius-lg)',
}

const cases: { title: string; puzzle: string; attempt: AttemptResult }[] = [
  { title: 'Flop, bet 33% (best)', puzzle: 'flop_unopened', attempt: attemptFixture('bet') },
  {
    title: 'Flop facing a raise, fold (best is call)',
    puzzle: 'facing_postflop_raise',
    attempt: attemptFixture('fold'),
  },
  {
    title: 'Pre-flop, raise',
    puzzle: 'preflop_bb_facing_open',
    attempt: attemptFixture('raise_preflop'),
  },
  {
    title: 'River, check (no "ahead" clause)',
    puzzle: 'river',
    attempt: attemptFixture('check_river'),
  },
  {
    title: 'Flop, Villain never continues (synthetic)',
    puzzle: 'flop_unopened',
    attempt: neverContinuesAttempt(),
  },
]

const entry: GalleryEntry = {
  title: 'Range',
  render: () => (
    <div>
      {cases.map(({ title, puzzle, attempt }) => (
        <figure key={title} style={{ margin: 'var(--space-6) 0 0' }}>
          <figcaption style={caption}>{title}</figcaption>
          <div style={box}>
            <RangePanel decision={decisionFromAttempt(puzzleFixture(puzzle), attempt)} />
          </div>
        </figure>
      ))}
    </div>
  ),
}

export default entry
