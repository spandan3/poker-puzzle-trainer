import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LineChart } from './LineChart'

const fmt = (y: number) => `${y.toFixed(1)} bb`

function setup(series: Parameters<typeof LineChart>[0]['series']) {
  const { container } = render(
    <LineChart title="EV lost" series={series} yLabel="bb" format={fmt} />,
  )
  return { container }
}

/** Opens the "Show data" disclosure (jsdom fires no toggle event by itself). */
function openData() {
  const details = document.querySelector('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
}

describe('LineChart', () => {
  it('renders the data table rows only while the disclosure is open', () => {
    setup([
      {
        label: 'A',
        points: [
          { x: 1, y: 1 },
          { x: 2, y: 2 },
        ],
      },
    ])
    const table = screen.getByRole('table', { name: 'EV lost' })
    expect(within(table).getAllByRole('row')).toHaveLength(1) // the header only
    openData()
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    const details = document.querySelector('details')!
    details.open = false
    fireEvent(details, new Event('toggle'))
    expect(within(table).getAllByRole('row')).toHaveLength(1)
  })

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
    openData()
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

  it('shows the empty message and no axis when no point has a value', () => {
    const { container } = render(
      <LineChart
        title="Range"
        yLabel="pts"
        format={fmt}
        empty="No range reads yet."
        series={[
          {
            label: 'A',
            points: [
              { x: 1, y: null },
              { x: 2, y: null },
            ],
          },
        ]}
      />,
    )
    expect(screen.getByText('No range reads yet.')).toBeInTheDocument()
    // a static message: plain text, not a live region
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByTestId('line-chart')).not.toBeInTheDocument()
    expect(container.querySelector('line')).toBeNull()
  })

  describe('tooltip', () => {
    const points = [1, 2, 3].map((x) => ({ x, y: x * 1.5 }))

    function hover(container: HTMLElement, clientX: number) {
      const svg = screen.getByTestId('line-chart')
      svg.getBoundingClientRect = () => ({ left: 0, width: 560, top: 0, height: 240 }) as DOMRect
      fireEvent.mouseMove(svg, { clientX })
      return container
    }

    it('says rolling average, with the last-value label text for the last point', () => {
      const { container } = setup([{ label: 'A', points }])
      hover(container, 560) // the far right: the last point
      const tip = screen.getByTestId('chart-tooltip')
      expect(tip).toHaveTextContent('Puzzle 3 · rolling average: 4.5 bb')
      expect(tip).toHaveAttribute('aria-hidden', 'true')
      // the value text is the one the last-value label draws
      const lastLabel = container.querySelector('text[class*="last"]')
      expect(lastLabel).toHaveTextContent('4.5 bb')
      fireEvent.mouseLeave(screen.getByTestId('line-chart'))
      expect(screen.queryByTestId('chart-tooltip')).not.toBeInTheDocument()
    })

    it('is placed against the SVG box, not the figure, with Show data open', () => {
      const { container } = render(
        <LineChart
          title="T"
          yLabel="bb"
          format={fmt}
          series={[
            { label: 'A', points },
            { label: 'B', points: points.map((p) => ({ ...p, y: p.y / 2 })) },
          ]}
        />,
      )
      openData()
      hover(container, 560)
      const tip = screen.getByTestId('chart-tooltip')
      const plot = screen.getByTestId('chart-plot')
      // the tooltip's containing box holds the SVG and nothing else that takes height
      expect(tip.parentElement).toBe(plot)
      expect(plot).toHaveClass('plot')
      expect([...plot.children].map((c) => c.tagName.toLowerCase())).toEqual(['svg', 'div'])
      expect(plot).not.toContainElement(document.querySelector('details'))
      expect(plot).not.toContainElement(container.querySelector('ul'))
      // so its % position is the hover dot's place in the SVG's own 560 x 240 box
      const dot = screen.getByTestId('hover-dot')
      expect(tip.style.left).toBe(`${(Number(dot.getAttribute('cx')) / 560) * 100}%`)
      expect(tip.style.top).toBe(`${(Number(dot.getAttribute('cy')) / 240) * 100}%`)
      expect(Number(dot.getAttribute('cx'))).toBe(560 - 64) // x = 3, the right edge of the plot
    })

    it('finds the nearest point and uses tooltipLabel when given', () => {
      render(
        <LineChart
          title="T"
          yLabel="bb"
          format={fmt}
          tooltipLabel={(n, v) => `n=${n} v=${v}`}
          series={[{ label: 'A', points }]}
        />,
      )
      const svg = screen.getByTestId('line-chart')
      svg.getBoundingClientRect = () => ({ left: 0, width: 560, top: 0, height: 240 }) as DOMRect
      fireEvent.mouseMove(svg, { clientX: 0 })
      expect(screen.getByTestId('chart-tooltip')).toHaveTextContent('n=1 v=1.5')
    })
  })

  describe('warm-up band', () => {
    const pts = (from: number, to: number) =>
      Array.from({ length: to - from + 1 }, (_, i) => ({ x: from + i, y: 1 }))

    it('shades x below the window and labels it', () => {
      const { container } = render(
        <LineChart
          title="T"
          yLabel="bb"
          format={fmt}
          warmUp={50}
          series={[{ label: 'A', points: pts(1, 100) }]}
        />,
      )
      const band = screen.getByTestId('warm-up')
      expect(band).toHaveTextContent('Fewer than 50 puzzles')
      const rect = band.querySelector('rect')!
      const left = Number(rect.getAttribute('x'))
      const right = left + Number(rect.getAttribute('width'))
      // the band starts at the plot's left edge and ends at sx(50): 40 + (50 - 1) / (100 - 1) * 456
      expect(left).toBe(40)
      expect(right).toBeCloseTo(40 + (49 / 99) * 456, 6)
      expect(container.querySelectorAll('rect')).toHaveLength(1)
    })

    it('draws none when every point is past the window', () => {
      render(
        <LineChart
          title="T"
          yLabel="bb"
          format={fmt}
          warmUp={50}
          series={[{ label: 'A', points: pts(50, 120) }]}
        />,
      )
      expect(screen.queryByTestId('warm-up')).not.toBeInTheDocument()
    })
  })
})
