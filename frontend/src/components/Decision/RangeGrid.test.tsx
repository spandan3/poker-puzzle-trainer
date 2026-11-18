import { render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { composite, contrastRatio, resolveTokens } from '../../lib/contrast'
import { RangeGrid } from './RangeGrid'

// Vitest turns `?raw` CSS imports into empty strings, so the real files are read from disk.
const read = (...parts: string[]) => readFileSync(resolve(import.meta.dirname, ...parts), 'utf8')
const tokens = resolveTokens(
  ['tokens.css', 'tokens.answer.css', 'tokens.results.css', 'tokens.ui.css'].map((f) =>
    read('../../styles', f),
  ),
)
const token = (name: string): string => {
  const v = tokens[name]
  if (v === undefined) throw new Error(`no token ${name}`)
  return v
}

function grid(fill: (r: number, c: number) => number | null) {
  return Array.from({ length: 13 }, (_, r) => Array.from({ length: 13 }, (_, c) => fill(r, c)))
}

describe('RangeGrid', () => {
  it('lines up 14 column headers (an empty corner and 13 ranks)', () => {
    render(<RangeGrid grid={grid(() => 0)} label="x" />)
    expect(screen.getAllByRole('columnheader')).toHaveLength(14)
    expect(screen.getAllByRole('rowheader')).toHaveLength(13)
  })

  it('renders 169 named cells plus A..2 headers', () => {
    render(<RangeGrid grid={grid(() => 0)} label="Start" />)
    expect(screen.getAllByRole('cell')).toHaveLength(169)
    expect(screen.getAllByRole('columnheader')).toHaveLength(14)
    expect(screen.getAllByRole('rowheader')).toHaveLength(13)
    expect(screen.getByRole('table', { name: 'Start' })).toBeInTheDocument()
  })

  it('names a weighted cell with its percentage', () => {
    render(<RangeGrid grid={grid((r, c) => (r === 0 && c === 1 ? 0.75 : 0))} label="x" />)
    expect(screen.getByRole('cell', { name: 'AKs, 75% weight' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'AA, 0% weight' })).toBeInTheDocument()
  })

  it('names a null cell as blocked', () => {
    render(<RangeGrid grid={grid((r, c) => (r === 1 && c === 0 ? null : 1))} label="x" />)
    expect(screen.getByRole('cell', { name: 'AKo, blocked' })).toBeInTheDocument()
    expect(screen.getAllByRole('cell', { name: /blocked$/ })).toHaveLength(1)
  })

  it('puts the weight in every cell title, and "blocked" in a blocked one', () => {
    render(
      <RangeGrid
        grid={grid((r, c) => (r === 1 && c === 0 ? null : r === 0 && c === 1 ? 0.756 : 0.5))}
        label="x"
      />,
    )
    expect(screen.getByRole('cell', { name: 'AKs, 76% weight' })).toHaveAttribute('title', '76%')
    expect(screen.getByRole('cell', { name: 'AKo, blocked' })).toHaveAttribute('title', 'blocked')
    for (const cell of screen.getAllByRole('cell')) {
      const label = cell.getAttribute('aria-label') ?? ''
      const weight = /, (\d+%) weight$/.exec(label)?.[1]
      expect(cell).toHaveAttribute('title', weight ?? 'blocked')
    }
  })
})

describe('RangeGrid contrast (B2)', () => {
  const cap = Number(token('--range-fill-max'))
  const text = token('--color-text')
  const sunken = token('--color-bg-sunken')

  it('keeps the label at 4.5:1 or better for every weight from 0 to 1', () => {
    expect(cap).toBeGreaterThan(0)
    expect(cap).toBeLessThanOrEqual(0.45)
    for (let i = 0; i <= 100; i++) {
      const w = i / 100
      const bg = composite(token('--range-fill'), Math.sqrt(w) * cap, sunken)
      expect(contrastRatio(text, bg), `weight ${w}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('keeps a 5% weight visibly apart from an empty cell', () => {
    const fillAt = (w: number) => composite(token('--range-fill'), Math.sqrt(w) * cap, sunken)
    expect(contrastRatio(fillAt(0.05), fillAt(0))).toBeGreaterThanOrEqual(1.05)
  })

  it('keeps the label readable over the blocked hatch', () => {
    const hatch = token('--range-blocked-hatch')
    expect(contrastRatio(text, composite(hatch, 1, sunken))).toBeGreaterThanOrEqual(4.5)
  })

  it('draws the cells on --color-bg-sunken with the fill capped through --range-fill-max', () => {
    const css = read('./RangeGrid.module.css')
    const cell = /\n\.cell \{([^}]*)\}/.exec(css)?.[1] ?? ''
    expect(cell).toMatch(/background:\s*var\(--color-bg-sunken\)/)
    expect(cell).toMatch(/color:\s*var\(--color-text\)/)
    const fill = /\.cell::before \{([^}]*)\}/.exec(css)?.[1] ?? ''
    expect(fill).toMatch(/opacity:\s*calc\(sqrt\(var\(--w, 0\)\) \* var\(--range-fill-max\)\)/)
    expect(css).not.toMatch(/data-strong/)
    expect(css).not.toMatch(/color-text-on-accent/)
  })
})
