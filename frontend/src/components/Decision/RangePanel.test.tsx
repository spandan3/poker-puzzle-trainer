import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { decisionFromAttempt } from '../../lib/decision'
import { bbLabel } from '../../lib/format'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
import { neverContinuesAttempt } from '../../test/synthetic'
import { RangePanel } from './RangePanel'

const betDecision = () => decisionFromAttempt(puzzleFixture('flop_unopened'), attemptFixture('bet'))

function stepGroup() {
  return screen.getByRole('radiogroup', { name: 'Step' })
}

describe('RangePanel', () => {
  it('lists the steps in order with the last selected', () => {
    const d = betDecision()
    render(<RangePanel decision={d} />)
    const radios = within(stepGroup()).getAllByRole('radio')
    expect(radios.map((r) => r.textContent)).toEqual(d.rangeSteps.map((s) => bbLabel(s.label)))
    expect(radios.at(-1)).toHaveAttribute('aria-checked', 'true')
    const last = d.rangeSteps.at(-1)
    expect(screen.getByText(new RegExp(`^${last?.combos.length} combos`))).toBeInTheDocument()
  })

  it('selecting the first step changes the grid and the combo count', () => {
    const d = betDecision()
    render(<RangePanel decision={d} />)
    const first = d.rangeSteps[0]
    const lastLabel = bbLabel(d.rangeSteps.at(-1)?.label ?? '')
    expect(screen.getByRole('table', { name: lastLabel })).toBeInTheDocument()
    fireEvent.click(within(stepGroup()).getAllByRole('radio')[0] as HTMLElement)
    expect(screen.getByRole('table', { name: bbLabel(first?.label ?? '') })).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: lastLabel })).not.toBeInTheDocument()
    expect(screen.getByText(new RegExp(`^${first?.combos.length} combos`))).toBeInTheDocument()
  })

  it('arrow keys move the step selection', () => {
    render(<RangePanel decision={betDecision()} />)
    const radios = within(stepGroup()).getAllByRole('radio')
    fireEvent.keyDown(radios.at(-1) as HTMLElement, { key: 'ArrowLeft' })
    expect(radios.at(-2)).toHaveAttribute('aria-checked', 'true')
  })

  it('continues-vs defaults to the best option and shows its fold share', () => {
    const d = betDecision()
    render(<RangePanel decision={d} />)
    const group = screen.getByRole('radiogroup', { name: 'Continues vs' })
    expect(within(group).getByRole('radio', { checked: true })).toHaveTextContent('Bet 33%')
    expect(within(group).queryByRole('radio', { name: 'Check' })).not.toBeInTheDocument()
    expect(screen.getByText('Folds: 34%')).toBeInTheDocument()
    fireEvent.click(within(group).getByRole('radio', { name: 'All-in' }))
    expect(screen.getByText('Folds: 83%')).toBeInTheDocument()
  })

  it('has no continues-vs selector when no option has a grid', () => {
    const d = betDecision()
    const options = d.options.map((o) => ({ ...o, continue_grid: null }))
    render(<RangePanel decision={{ ...d, options }} />)
    expect(screen.queryByRole('radiogroup', { name: 'Continues vs' })).not.toBeInTheDocument()
    expect(screen.queryByText(/^Folds:/)).not.toBeInTheDocument()
  })

  it('shows the headline with both clauses', () => {
    render(<RangePanel decision={betDecision()} />)
    expect(
      screen.getByText("You're ahead of 47% of this range; your equity is 46%."),
    ).toBeInTheDocument()
  })

  it('drops the ahead clause on the river', () => {
    const d = decisionFromAttempt(puzzleFixture('river'), attemptFixture('check_river'))
    render(<RangePanel decision={d} />)
    expect(screen.queryByText(/ahead of/)).not.toBeInTheDocument()
    expect(screen.getByText(/^Your equity against this range is/)).toBeInTheDocument()
  })

  it('shows the category table, and no heading when categories are null', () => {
    const d = betDecision()
    const { rerender } = render(<RangePanel decision={d} />)
    expect(screen.getByRole('heading', { name: 'Hero vs range' })).toBeInTheDocument()
    expect(screen.getByRole('table', { name: /part of the range/ })).toBeInTheDocument()
    rerender(<RangePanel decision={{ ...d, categories: null }} />)
    expect(screen.queryByRole('heading', { name: 'Hero vs range' })).not.toBeInTheDocument()
    expect(screen.queryByRole('table', { name: /part of the range/ })).not.toBeInTheDocument()
  })

  it('handles Villain never continuing without NaN', () => {
    const d = decisionFromAttempt(puzzleFixture('flop_unopened'), neverContinuesAttempt())
    const { container } = render(<RangePanel decision={d} />)
    expect(container).not.toHaveTextContent('NaN')
  })
})
