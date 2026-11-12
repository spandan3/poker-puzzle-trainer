import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { statsFixture } from '../../test/fixture'
import { Breakdowns } from './Breakdowns'

const breakdowns = statsFixture().breakdowns

describe('Breakdowns', () => {
  it('starts on Street with the rows in the API order', () => {
    render(<Breakdowns breakdowns={breakdowns} />)
    expect(screen.getByRole('tab', { name: 'Street' })).toHaveAttribute('aria-selected', 'true')
    const rows = within(screen.getByRole('tabpanel')).getAllByRole('row')
    expect(rows.slice(1).map((r) => within(r).getByRole('rowheader').textContent)).toEqual(
      breakdowns.street.map((r) => r.label),
    )
    // pre-flop: 32 puzzles, 100% accuracy, EV lost 0.06 bb, equity error 8.6 pts
    expect(rows[1]).toHaveTextContent('Pre-flop')
    expect(rows[1]).toHaveTextContent('32')
    expect(rows[1]).toHaveTextContent('100%')
    expect(rows[1]).toHaveTextContent('0.06 bb')
    expect(rows[1]).toHaveTextContent('8.6 pts')
  })

  it('switches tabs by click and with the arrow keys', async () => {
    const user = userEvent.setup()
    render(<Breakdowns breakdowns={breakdowns} />)
    await user.click(screen.getByRole('tab', { name: 'Action' }))
    expect(
      within(screen.getByRole('tabpanel')).getByRole('rowheader', { name: 'Fold' }),
    ).toBeVisible()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Villain' })).toHaveAttribute('aria-selected', 'true')
    expect(
      within(screen.getByRole('tabpanel')).getByRole('rowheader', { name: 'TAG' }),
    ).toBeVisible()
    await user.keyboard('{Home}')
    expect(screen.getByRole('tab', { name: 'Street' })).toHaveFocus()
  })

  it('shows EV lost with two fixed decimals so the column lines up', async () => {
    const user = userEvent.setup()
    const rows = [
      { ...breakdowns.profile[0]!, key: 'a', label: 'A', ev_lost_bb_avg: 0 },
      { ...breakdowns.profile[0]!, key: 'b', label: 'B', ev_lost_bb_avg: 0.7 },
    ]
    render(<Breakdowns breakdowns={{ ...breakdowns, profile: rows }} />)
    await user.click(screen.getByRole('tab', { name: 'Villain' }))
    const cells = within(screen.getByRole('tabpanel')).getAllByRole('row')
    expect(cells[1]).toHaveTextContent('0.00 bb')
    expect(cells[2]).toHaveTextContent('0.70 bb')
  })

  it('says so when a tab has no rows', () => {
    render(<Breakdowns breakdowns={{ street: [], action: [], profile: [] }} />)
    expect(screen.getByText('No puzzles yet.')).toBeVisible()
  })
})
