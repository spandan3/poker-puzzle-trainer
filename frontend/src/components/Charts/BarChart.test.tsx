import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BarChart } from './BarChart'

const bars = [
  { label: 'Nov 10', value: 2 },
  { label: 'Nov 11', value: 5 },
  { label: 'Nov 12', value: 0 },
]

describe('BarChart', () => {
  it('draws a bar per day and marks the ones that reach the goal', () => {
    const { container } = render(<BarChart title="Puzzles per day" bars={bars} goal={5} />)
    const rects = container.querySelectorAll('rect')
    expect(rects).toHaveLength(3)
    expect(Array.from(rects).map((r) => r.hasAttribute('data-met'))).toEqual([false, true, false])
  })

  it('draws the goal line at the goal height and labels it', () => {
    const { container } = render(<BarChart title="Puzzles per day" bars={bars} goal={4} />)
    expect(screen.getByTestId('goal-line')).toBeInTheDocument()
    expect(container.textContent).toContain('Goal 4')
    // a bar of 5 is taller than the goal line is high
    const goalY = Number(screen.getByTestId('goal-line').getAttribute('y1'))
    const tall = container.querySelectorAll('rect')[1]!
    expect(Number(tall.getAttribute('y'))).toBeLessThan(goalY)
  })

  it('has a data table with a row per bar and the goal in its caption', () => {
    render(<BarChart title="Puzzles per day" bars={bars} goal={5} />)
    const table = screen.getByRole('table', { name: /Puzzles per day.*goal 5/ })
    expect(within(table).getAllByRole('row')).toHaveLength(1) // closed: the header only
    const details = document.querySelector('details')!
    details.open = true
    fireEvent(details, new Event('toggle'))
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(4)
    expect(rows[2]).toHaveTextContent('Nov 11')
    expect(rows[2]).toHaveTextContent('5')
  })

  it('copes with no bars', () => {
    const { container } = render(<BarChart title="Puzzles per day" bars={[]} goal={3} />)
    expect(container.innerHTML).not.toContain('NaN')
  })
})
