import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RangeGrid } from './RangeGrid'

function grid(fill: (r: number, c: number) => number | null) {
  return Array.from({ length: 13 }, (_, r) => Array.from({ length: 13 }, (_, c) => fill(r, c)))
}

describe('RangeGrid', () => {
  it('renders 169 named cells plus A..2 headers', () => {
    render(<RangeGrid grid={grid(() => 0)} label="Start" />)
    expect(screen.getAllByRole('gridcell')).toHaveLength(169)
    expect(screen.getAllByRole('columnheader')).toHaveLength(13)
    expect(screen.getAllByRole('rowheader')).toHaveLength(13)
    expect(screen.getByRole('grid', { name: 'Start' })).toBeInTheDocument()
  })

  it('names a weighted cell with its percentage', () => {
    render(<RangeGrid grid={grid((r, c) => (r === 0 && c === 1 ? 0.75 : 0))} label="x" />)
    expect(screen.getByRole('gridcell', { name: 'AKs, 75% weight' })).toBeInTheDocument()
    expect(screen.getByRole('gridcell', { name: 'AA, 0% weight' })).toBeInTheDocument()
  })

  it('names a null cell as blocked', () => {
    render(<RangeGrid grid={grid((r, c) => (r === 1 && c === 0 ? null : 1))} label="x" />)
    expect(screen.getByRole('gridcell', { name: 'AKo, blocked' })).toBeInTheDocument()
    expect(screen.getAllByRole('gridcell', { name: /blocked$/ })).toHaveLength(1)
  })
})
