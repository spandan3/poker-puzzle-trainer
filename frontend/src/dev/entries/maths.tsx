import type { CSSProperties } from 'react'
import type { AttemptResult } from '../../api/types'
import { MathsPanel } from '../../components/Decision/MathsPanel'
import { decisionFromAttempt } from '../../lib/decision'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
import { bbCallAttempt, neverContinuesAttempt } from '../../test/synthetic'
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

// every attempt fixture with the puzzle it was made on
const cases: { title: string; puzzle: string; attempt: AttemptResult }[] = [
  { title: 'Flop, bet 33% (best)', puzzle: 'flop_unopened', attempt: attemptFixture('bet') },
  {
    title: 'Flop facing a raise, fold (best is call)',
    puzzle: 'facing_postflop_raise',
    attempt: attemptFixture('fold'),
  },
  {
    title: 'Flop facing a raise, call (best)',
    puzzle: 'facing_postflop_raise',
    attempt: attemptFixture('call'),
  },
  {
    title: 'Pre-flop, raise (preflop_size note)',
    puzzle: 'preflop_bb_facing_open',
    attempt: attemptFixture('raise_preflop'),
  },
  {
    title: 'Pre-flop BB, call out of position (realisation 80%; synthetic, from the raise fixture)',
    puzzle: 'preflop_bb_facing_open',
    attempt: bbCallAttempt(),
  },
  {
    title: 'Pre-flop, fold',
    puzzle: 'preflop_btn_first_in',
    attempt: attemptFixture('fold_preflop'),
  },
  {
    title: 'River, check (look-ahead branches)',
    puzzle: 'river',
    attempt: attemptFixture('check_river'),
  },
  {
    title: 'Flop, custom size (EV above the marked best)',
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
  title: 'Maths',
  render: () => (
    <div>
      {cases.map(({ title, puzzle, attempt }) => (
        <figure key={title} style={{ margin: 'var(--space-6) 0 0' }}>
          <figcaption style={caption}>{title}</figcaption>
          <div style={box}>
            <MathsPanel decision={decisionFromAttempt(puzzleFixture(puzzle), attempt)} />
          </div>
        </figure>
      ))}
    </div>
  ),
}

export default entry
