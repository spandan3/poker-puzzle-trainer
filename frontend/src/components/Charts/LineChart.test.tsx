import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LineChart } from './LineChart'

const fmt = (y: number) => `${y.toFixed(1)} bb`

function setup(series: Parameters<typeof LineChart>[0]['series']) {
  const { container } = render(
    <LineChart title="EV lost" series={series} yLabel="bb" format={fmt} />,
  )
  return { container }
}

describe('LineChart', () => {
  it('draws one path per series', () => {
    const { container } = setup([
      {
        label: 'A',
        points: [
          { x: 1, y: 1 },
          { x: 2, y: 2 },
        ],
      },
      {
        label: 'B',
        points: [
          { x: 1, y: 2 },
          { x: 2, y: 1 },
        ],
      },
    ])
    expect(container.querySelectorAll('path')).toHaveLength(2)
  })

  it('leaves a gap for a null: the path restarts with a new M', () => {
    const { container } = setup([
      {
        label: 'A',
        points: [
          { x: 1, y: 1 },
          { x: 2, y: null },
          { x: 3, y: 2 },
          { x: 4, y: 3 },
        ],
      },
    ])
    const d = container.querySelector('path')!.getAttribute('d')!
    expect(d.match(/M/g)).toHaveLength(2)
    expect(d.match(/L/g)).toHaveLength(1)
  })

  it('labels the last value and names the chart', () => {
    setup([
      {
        label: 'A',
        points: [
          { x: 1, y: 1 },
          { x: 2, y: 2.25 },
        ],
      },
    ])
    expect(screen.getByRole('img', { name: 'EV lost' })).toBeInTheDocument()
    expect(screen.getByText('2.3 bb', { selector: 'svg text' })).toBeInTheDocument()
  })

  it('has a data table with one row per point (a null as a dash)', () => {
    setup([
      {
        label: 'A',
        points: [
          { x: 1, y: 1 },
          { x: 2, y: null },
          { x: 3, y: 2 },
        ],
      },
    ])
    const table = screen.getByRole('table', { name: 'EV lost' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(4) // header + 3
    expect(within(rows[1]!).getByRole('rowheader')).toHaveTextContent('1')
    expect(within(rows[2]!).getAllByRole('cell')[0]).toHaveTextContent('—')
    expect(within(rows[3]!).getAllByRole('cell')[0]).toHaveTextContent('2.0 bb')
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((h) => h.textContent),
    ).toEqual(['Puzzle', 'bb'])
  })

  it('renders with no data and with one point', () => {
    const { container } = setup([{ label: 'A', points: [] }])
    expect(container.querySelector('path')?.getAttribute('d')).toBe('')
  })

  it('handles a single point', () => {
    const { container } = setup([{ label: 'A', points: [{ x: 5, y: 1 }] }])
    expect(container.querySelector('circle')).not.toBeNull()
    expect(container.innerHTML).not.toContain('NaN')
  })
})
