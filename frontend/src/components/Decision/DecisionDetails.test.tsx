import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { decisionFromAttempt } from '../../lib/decision'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
import { DecisionDetails } from './DecisionDetails'

const decision = decisionFromAttempt(puzzleFixture('flop_unopened'), attemptFixture('bet'))

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('DecisionDetails', () => {
  it('has Options, Maths and Range tabs, Options selected, without a Hand tab', () => {
    render(<DecisionDetails decision={decision} />)
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual([
      'Options',
      'Maths',
      'Range',
    ])
    expect(screen.getByRole('tab', { name: 'Options' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('table')).toBeVisible()
    expect(screen.getByRole('tabpanel')).toHaveAccessibleName('Options')
  })

  it('has a hidden Details heading and a focusable selected panel', () => {
    render(<DecisionDetails decision={decision} />)
    expect(screen.getByRole('heading', { level: 2, name: 'Details' })).toBeInTheDocument()
    expect(screen.getByRole('tabpanel')).toHaveAttribute('tabindex', '0')
  })

  it('adds a Hand tab when given its content', async () => {
    const user = userEvent.setup()
    render(<DecisionDetails decision={decision} handTab={<p>the hand</p>} />)
    expect(screen.getAllByRole('tab')).toHaveLength(4)
    await user.click(screen.getByRole('tab', { name: 'Hand' }))
    expect(screen.getByText('the hand')).toBeVisible()
  })

  it('puts Why first and selected when given, and still honours a stored tab', async () => {
    const user = userEvent.setup()
    const first = render(
      <DecisionDetails decision={decision} whyTab={<p>the why</p>} handTab={<p>the hand</p>} />,
    )
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual([
      'Why',
      'Options',
      'Maths',
      'Range',
      'Hand',
    ])
    expect(screen.getByRole('tab', { name: 'Why' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('the why')).toBeVisible()
    await user.click(screen.getByRole('tab', { name: 'Options' }))
    first.unmount()
    render(<DecisionDetails decision={decision} whyTab={<p>the why</p>} />)
    expect(screen.getByRole('tab', { name: 'Options' })).toHaveAttribute('aria-selected', 'true')
  })

  it('cycles five tabs with the arrow keys', async () => {
    const user = userEvent.setup()
    render(<DecisionDetails decision={decision} whyTab={<p>w</p>} handTab={<p>h</p>} />)
    screen.getByRole('tab', { name: 'Why' }).focus()
    await user.keyboard('{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'Hand' })).toHaveFocus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Why' })).toHaveFocus()
    await user.keyboard('{ArrowRight}{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Maths' })).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{Home}')
    expect(screen.getByRole('tab', { name: 'Why' })).toHaveFocus()
  })

  it('moves the selection with the arrow keys', async () => {
    const user = userEvent.setup()
    render(<DecisionDetails decision={decision} />)
    screen.getByRole('tab', { name: 'Options' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Maths' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Maths' })).toHaveFocus()
    await user.keyboard('{End}')
    expect(screen.getByRole('tab', { name: 'Range' })).toHaveFocus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Options' })).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'Range' })).toHaveAttribute('aria-selected', 'true')
  })

  it('links each tab to its panel', () => {
    render(<DecisionDetails decision={decision} />)
    const tab = screen.getByRole('tab', { name: 'Options' })
    expect(document.getElementById(tab.getAttribute('aria-controls')!)).toHaveAttribute(
      'role',
      'tabpanel',
    )
  })

  it('restores the selected tab from storage', async () => {
    const user = userEvent.setup()
    const first = render(<DecisionDetails decision={decision} />)
    await user.click(screen.getByRole('tab', { name: 'Range' }))
    expect(window.localStorage.getItem('ppt.resultTab')).toBe('range')
    first.unmount()
    render(<DecisionDetails decision={decision} />)
    expect(screen.getByRole('tab', { name: 'Range' })).toHaveAttribute('aria-selected', 'true')
  })

  it('falls back to Options when the stored tab is not there', () => {
    window.localStorage.setItem('ppt.resultTab', 'hand')
    render(<DecisionDetails decision={decision} />)
    expect(screen.getByRole('tab', { name: 'Options' })).toHaveAttribute('aria-selected', 'true')
  })

  it('still works when storage throws', async () => {
    const user = userEvent.setup()
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    render(<DecisionDetails decision={decision} />)
    expect(screen.getByRole('tab', { name: 'Options' })).toHaveAttribute('aria-selected', 'true')
    await user.click(screen.getByRole('tab', { name: 'Maths' }))
    expect(screen.getByRole('tab', { name: 'Maths' })).toHaveAttribute('aria-selected', 'true')
  })
})
