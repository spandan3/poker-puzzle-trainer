import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { attemptFixture } from '../../test/fixture'
import { CategoryTable } from './CategoryTable'

describe('CategoryTable', () => {
  it('has the five columns and a row per category', () => {
    const cats = attemptFixture('bet').categories ?? []
    render(<CategoryTable categories={cats} hero={{ ahead: 0.47, equity: 0.46 }} />)
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Category',
      'Share of range',
      "You're ahead",
      'Your equity',
      'Win / Tie / Lose',
    ])
    expect(screen.getAllByRole('rowheader')).toHaveLength(cats.length + 1)
  })

  it('shows a dash for ahead when there is none (river)', () => {
    render(<CategoryTable categories={[]} hero={{ ahead: null, equity: 0.5 }} />)
    const row = screen.getByRole('row', { name: /Whole range/ })
    expect(within(row).getByText('—')).toBeInTheDocument()
  })
})
