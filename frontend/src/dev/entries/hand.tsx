import type { CSSProperties } from 'react'
import type { AttemptResult } from '../../api/types'
import { HandReveal } from '../../components/HandReveal/HandReveal'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
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
  {
    title: 'Flop, bet 33% (run-out, Hero wins)',
    puzzle: 'flop_unopened',
    attempt: attemptFixture('bet'),
  },
  {
    title: 'Flop facing a raise, fold (no run-out)',
    puzzle: 'facing_postflop_raise',
    attempt: attemptFixture('fold'),
  },
  {
    title: 'Pre-flop, fold (no run-out)',
    puzzle: 'preflop_bb_facing_open',
    attempt: attemptFixture('fold_preflop'),
  },
  { title: 'River, check', puzzle: 'river', attempt: attemptFixture('check_river') },
]

const entry: GalleryEntry = {
  title: 'Hand',
  render: () => (
    <div>
      {cases.map(({ title, puzzle, attempt }) => (
        <figure key={title} style={{ margin: 'var(--space-6) 0 0' }}>
          <figcaption style={caption}>{title}</figcaption>
          <div style={box}>
            <HandReveal view={puzzleFixture(puzzle)} result={attempt} />
          </div>
        </figure>
      ))}
    </div>
  ),
}

export default entry
