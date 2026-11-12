import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { decisionFromAttempt } from '../../lib/decision'
import { formatEvBb } from '../../lib/format'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
import { neverContinuesAttempt } from '../../test/synthetic'
import { MathsPanel } from './MathsPanel'

function columns() {
  return screen.getAllByRole('region')
}

describe('MathsPanel', () => {
  it('chosen fold, best call: two columns, and EV lost from the grade', () => {
    const d = decisionFromAttempt(puzzleFixture('facing_postflop_raise'), attemptFixture('fold'))
    render(<MathsPanel decision={d} />)
    const cols = columns()
    expect(cols).toHaveLength(2)
    const [yours, best] = cols
    if (!yours || !best) throw new Error('two columns')
    expect(within(yours).getByRole('heading', { level: 3 })).toHaveTextContent(/Your play.*Fold/)
    expect(within(best).getByRole('heading', { level: 3 })).toHaveTextContent(/Best play.*Call/)
    expect(within(best).getByText('= 37.5% × (11 bb + 3 bb) − 3 bb')).toBeInTheDocument()
    expect(within(yours).getByText('EV = 0 (folding is the baseline)')).toBeInTheDocument()
    expect(screen.getByText(/^EV lost = best − yours =/)).toHaveTextContent(
      `EV lost = best − yours = ${formatEvBb(d.grade.ev_loss_bb)}`,
    )
  })

  it('chosen = best: one column', () => {
    const d = decisionFromAttempt(puzzleFixture('flop_unopened'), attemptFixture('bet'))
    render(<MathsPanel decision={d} />)
    const cols = columns()
    expect(cols).toHaveLength(1)
    const heading = within(cols[0] as HTMLElement).getByRole('heading', { level: 3 })
    expect(heading).toHaveTextContent(/Your play.*Best play.*Bet 33%/)
    // the branch table is a real table with column headers
    const table = screen.getByRole('table')
    expect(within(table).getByRole('columnheader', { name: 'Share' })).toBeInTheDocument()
    expect(within(table).getByRole('rowheader', { name: 'Villain calls' })).toBeInTheDocument()
    expect(screen.getByText(/^EV lost/)).toHaveTextContent('EV lost = best − yours = 0 bb')
  })

  it('custom size above the marked best: EV lost is the grade value, never negative', () => {
    const d = decisionFromAttempt(puzzleFixture('custom_allowed'), attemptFixture('custom'))
    render(<MathsPanel decision={d} />)
    expect(columns()).toHaveLength(2)
    expect(screen.getByText(/^EV lost/)).toHaveTextContent(
      `EV lost = best − yours = ${formatEvBb(d.grade.ev_loss_bb)}`,
    )
    expect(screen.getByRole('heading', { name: /Your play.*Bet 1 bb/ })).toBeInTheDocument()
  })

  it('Villain never continues: one branch, no equity, no NaN', () => {
    const d = decisionFromAttempt(puzzleFixture('flop_unopened'), neverContinuesAttempt())
    const { container } = render(<MathsPanel decision={d} />)
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(2)
    expect(within(table).getByRole('rowheader', { name: 'Villain folds' })).toBeInTheDocument()
    expect(container.textContent).not.toContain('NaN')
  })

  it('shows the option notes', () => {
    const d = decisionFromAttempt(
      puzzleFixture('preflop_bb_facing_open'),
      attemptFixture('raise_preflop'),
    )
    render(<MathsPanel decision={d} />)
    const text = d.simplifications.find((s) => s.code === 'preflop_size')?.text ?? ''
    expect(screen.getByText(text)).toBeInTheDocument()
  })
})
