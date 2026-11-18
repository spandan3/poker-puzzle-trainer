import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { statsFixture } from '../../test/fixture'
import { DailyGoal } from './DailyGoal'

const days = statsFixture().days

describe('DailyGoal', () => {
  it('shows the stats goal, the summary and the chart, and no goal input', () => {
    render(<DailyGoal days={days} />)
    expect(screen.getByText(/Goal: 3 a day/)).toBeVisible()
    expect(screen.getByText(/Today 1 \/ 3/)).toBeVisible()
    expect(screen.getByTestId('bar-chart')).toHaveAccessibleName(/goal 3/)
    expect(screen.queryByRole('spinbutton')).toBeNull()
  })

  it('links to Settings; a plain click goes through onNavigate', async () => {
    const onNavigate = vi.fn()
    render(<DailyGoal days={days} onNavigate={onNavigate} />)
    const link = screen.getByRole('link', { name: 'Change in Settings' })
    expect(link).toHaveAttribute('href', '/settings')
    await userEvent.click(link)
    expect(onNavigate).toHaveBeenCalledWith('settings')
  })

  it('shows the UTC note only when asked', () => {
    const { rerender } = render(<DailyGoal days={days} />)
    expect(screen.queryByTestId('utc-note')).toBeNull()
    rerender(<DailyGoal days={days} utcNote />)
    expect(screen.getByTestId('utc-note')).toBeVisible()
  })
})
