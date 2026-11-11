import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { SeatInfo } from '../../lib/seats'
import { Seat } from './Seat'

const villain: SeatInfo = {
  slot: 'top',
  name: 'Villain',
  position: 'BTN',
  stackChips: 195,
  betChips: 5,
  isHero: false,
  isButton: true,
  cards: [null, null],
  faceDown: true,
  profile: { label: 'LAG', description: 'Loose-aggressive: wide ranges.' },
  showProfile: true,
}

describe('Seat', () => {
  it('shows name, position, stack and bet in bb', () => {
    render(<Seat seat={villain} />)
    const seat = screen.getByRole('group', { name: 'Villain, BTN' })
    expect(seat).toHaveAttribute('data-slot', 'top')
    expect(within(seat).getByText('BTN')).toBeInTheDocument()
    expect(within(seat).getByText('97.5 bb')).toBeInTheDocument()
    expect(within(seat).getByText('2.5 bb')).toBeInTheDocument()
    expect(within(seat).getByRole('img', { name: 'Dealer button' })).toBeInTheDocument()
    expect(within(seat).getAllByRole('img', { name: 'face-down card' })).toHaveLength(2)
  })

  it('shows the profile as a button described by its tooltip', () => {
    render(<Seat seat={villain} />)
    const badge = screen.getByRole('button', { name: 'Profile LAG' })
    expect(badge).toHaveAttribute('type', 'button')
    expect(badge).toHaveAccessibleDescription('Loose-aggressive: wide ranges.')
    expect(screen.getByRole('tooltip', { hidden: true })).toHaveAttribute('data-state', 'closed')
  })

  it('opens the tooltip on focus and closes it on Escape and on blur', async () => {
    const user = userEvent.setup()
    render(<Seat seat={villain} />)
    const tooltip = screen.getByRole('tooltip', { hidden: true })
    await user.tab()
    expect(screen.getByRole('button', { name: 'Profile LAG' })).toHaveFocus()
    expect(tooltip).toHaveAttribute('data-state', 'open')
    await user.keyboard('{Escape}')
    expect(tooltip).toHaveAttribute('data-state', 'closed')
    await user.tab({ shift: true })
    await user.tab()
    expect(tooltip).toHaveAttribute('data-state', 'open')
    await user.tab()
    expect(tooltip).toHaveAttribute('data-state', 'closed')
  })

  it('keeps the tooltip open while the pointer is over the badge or the tooltip', () => {
    render(<Seat seat={villain} />)
    const badge = screen.getByRole('button', { name: 'Profile LAG' })
    const tooltip = screen.getByRole('tooltip', { hidden: true })
    const wrapper = badge.parentElement!
    expect(wrapper).toContainElement(tooltip)
    fireEvent.pointerEnter(wrapper)
    expect(tooltip).toHaveAttribute('data-state', 'open')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(tooltip).toHaveAttribute('data-state', 'closed')
    fireEvent.pointerEnter(wrapper)
    fireEvent.pointerLeave(wrapper)
    expect(tooltip).toHaveAttribute('data-state', 'closed')
  })

  it('hides the profile when showProfile is off', () => {
    render(<Seat seat={{ ...villain, showProfile: false }} />)
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.queryByText(/LAG/)).toBeNull()
    expect(screen.queryByText('Loose-aggressive: wide ranges.')).toBeNull()
  })

  it('has no bet and no dealer button when there are none', () => {
    const { container } = render(<Seat seat={{ ...villain, betChips: 0, isButton: false }} />)
    expect(container.querySelector('[data-part="bet"]')).toBeNull()
    expect(screen.queryByRole('img', { name: 'Dealer button' })).toBeNull()
  })

  it('marks an all-in stack', () => {
    render(<Seat seat={{ ...villain, stackChips: 0 }} />)
    expect(screen.getByText('All-in')).toBeInTheDocument()
  })

  it("shows Hero's cards face up", () => {
    render(
      <Seat
        seat={{
          ...villain,
          slot: 'bottom',
          name: 'Hero',
          isHero: true,
          cards: ['Ah', 'Td'],
          faceDown: false,
          profile: undefined,
          showProfile: false,
        }}
      />,
    )
    expect(screen.getByRole('img', { name: 'Ace of hearts' })).toHaveAttribute('data-suit', 'h')
    expect(screen.getByRole('img', { name: 'Ten of diamonds' })).toHaveAttribute('data-suit', 'd')
  })
})
