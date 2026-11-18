import { cleanup, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { decisionFromAttempt } from '../../lib/decision'
import { formatEvBb } from '../../lib/format'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
import {
  bbCallAttempt,
  customBelowListedBestAttempt,
  neverContinuesAttempt,
  potOddsTieAttempt,
} from '../../test/synthetic'
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
    expect(within(best).getByText('= 37.6% × (11 bb + 3 bb) − 3 bb')).toBeInTheDocument()
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

  it('custom size that beats the listed best: one column, it is the best play', () => {
    const d = decisionFromAttempt(puzzleFixture('custom_allowed'), attemptFixture('custom'))
    render(<MathsPanel decision={d} />)
    const cols = columns()
    expect(cols).toHaveLength(1)
    const heading = within(cols[0] as HTMLElement).getByRole('heading', { level: 3 })
    expect(heading).toHaveTextContent(/Your play.*Best play.*Bet 1 bb/)
    expect(screen.getByText(/^EV lost/)).toHaveTextContent('EV lost = best − yours = 0 bb')
  })

  it('custom size above the marked best (a pre-M9 row): EV lost is the grade value, never negative', () => {
    const d = decisionFromAttempt(puzzleFixture('custom_allowed'), customBelowListedBestAttempt())
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

  it('a pre-flop BB call: the realisation factor and realised equity are shown', () => {
    const d = decisionFromAttempt(puzzleFixture('preflop_bb_facing_open'), bbCallAttempt())
    render(<MathsPanel decision={d} />)
    const [yours, best] = columns()
    if (!yours || !best) throw new Error('two columns')
    expect(within(yours).getByRole('heading', { level: 3 })).toHaveTextContent(/Your play.*Call/)
    const realisation = within(yours).getByText('Realisation (out of position, pre-flop)')
    expect(realisation.parentElement).toHaveTextContent('80%')
    expect(within(yours).getByText('EV = r × e × (pot + call) − call')).toBeInTheDocument()
    expect(
      within(yours).getByText('= 0.80 × 51.2% × (3.5 bb + 1.5 bb) − 1.5 bb').parentElement,
    ).toHaveTextContent('0.55 bb')
    expect(
      within(yours).getByText(
        'Your realised equity (80% of 51.2% = 41.0%) is above the 30.0% pot odds, so calling beats folding',
      ),
    ).toBeInTheDocument()
    // the best play (a raise): its Villain-calls branch is worked with r × e
    expect(
      within(best).getByText('0.80 × 46.2% × (3.5 bb + 5 bb + 3.5 bb) − 5 bb'),
    ).toBeInTheDocument()
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

  it('an amount never splits from its unit: no plain space before "bb" (Task 6 N3)', () => {
    const d = decisionFromAttempt(puzzleFixture('facing_postflop_raise'), attemptFixture('fold'))
    const { container } = render(<MathsPanel decision={d} />)
    const text = container.textContent ?? ''
    expect(text).toContain('3\u00a0bb')
    expect(text).not.toMatch(/\d bb/)
    // the formula still reads the same to assistive tech and to tests (whitespace-normalised)
    expect(screen.getByText('= 37.6% × (11 bb + 3 bb) − 3 bb')).toBeInTheDocument()
  })

  it('branch rows keep their amounts on one line too', () => {
    const d = decisionFromAttempt(puzzleFixture('river'), attemptFixture('check_river'))
    const { container } = render(<MathsPanel decision={d} />)
    const table = container.querySelector('table')
    expect(table).not.toBeNull()
    expect(table!.textContent).toContain('\u00a0bb')
    expect(table!.textContent).not.toMatch(/\d bb/)
  })

  it('a pot-odds tie says "exactly" or "just short", and every formula still reproduces', () => {
    const view = puzzleFixture('facing_postflop_raise')
    render(<MathsPanel decision={decisionFromAttempt(view, potOddsTieAttempt(0.2143))} />)
    expect(
      screen.getByText('21.4% is exactly the 21.4% pot odds, so calling beats folding'),
    ).toBeInTheDocument()
    expect(screen.queryByText('EV (solver value)')).toBeNull()
    cleanup()
    render(<MathsPanel decision={decisionFromAttempt(view, potOddsTieAttempt(0.21426))} />)
    // chosen call, best fold: both columns carry the pot-odds line
    expect(
      screen.getAllByText('21.4% falls just short of the 21.4% pot odds, so folding beats calling'),
    ).toHaveLength(2)
    expect(screen.queryByText('EV (solver value)')).toBeNull()
    expect(screen.queryByText(/is (above|below)/)).toBeNull()
  })
})
