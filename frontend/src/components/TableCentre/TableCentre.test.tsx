import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TableCentre } from './TableCentre'

describe('TableCentre', () => {
  it('shows the pot in bb', () => {
    render(<TableCentre board={[]} potChips={263} potOdds={null} showPotOdds />)
    expect(screen.getByText('Pot 131.5 bb')).toBeInTheDocument()
  })

  it('shows pot odds and the equity needed when present and enabled', () => {
    render(<TableCentre board={['9d', 'Jd', '2c']} potChips={40} potOdds={0.3425} showPotOdds />)
    expect(screen.getByText('Pot odds: call needs 34% equity')).toBeInTheDocument()
  })

  it('hides pot odds when null', () => {
    render(<TableCentre board={['9d', 'Jd', '2c']} potChips={40} potOdds={null} showPotOdds />)
    expect(screen.queryByText(/Pot odds/)).not.toBeInTheDocument()
  })

  it('hides pot odds when switched off', () => {
    render(
      <TableCentre board={['9d', 'Jd', '2c']} potChips={40} potOdds={0.25} showPotOdds={false} />,
    )
    expect(screen.queryByText(/Pot odds/)).not.toBeInTheDocument()
    expect(screen.queryByText(/equity/)).not.toBeInTheDocument()
  })

  it('draws dealt cards and fills up to five slots', () => {
    const { container } = render(
      <TableCentre board={['9d', 'Jd', '2c']} potChips={40} potOdds={null} showPotOdds />,
    )
    expect(container.querySelectorAll('[data-face]')).toHaveLength(5)
    expect(container.querySelectorAll('[data-face="up"]')).toHaveLength(3)
    expect(container.querySelectorAll('[data-face="empty"]')).toHaveLength(2)
    // the cards are described by the board summary, so the drawing itself is hidden
    expect(screen.queryAllByRole('img')).toHaveLength(0)
  })

  it('draws five empty slots pre-flop without any card identity', () => {
    const { container } = render(<TableCentre board={[]} potChips={3} potOdds={null} showPotOdds />)
    expect(container.querySelectorAll('[data-face="empty"]')).toHaveLength(5)
    expect(container.querySelectorAll('[data-rank],[data-suit]')).toHaveLength(0)
    expect(screen.queryAllByRole('img')).toHaveLength(0)
  })

  it('summarises the board for assistive technology', () => {
    render(<TableCentre board={['9h', 'Jd', '2c']} potChips={40} potOdds={null} showPotOdds />)
    expect(
      screen.getByText('Board: Nine of hearts, Jack of diamonds, Two of clubs'),
    ).toBeInTheDocument()
  })

  it('says the board is empty pre-flop', () => {
    render(<TableCentre board={[]} potChips={3} potOdds={null} showPotOdds />)
    expect(screen.getByText('Board: no cards yet')).toBeInTheDocument()
  })

  it('slides in only the cards from dealFrom, staggered', () => {
    const { container } = render(
      <TableCentre
        board={['Ah', 'Kd', '7c', '2s', '9h']}
        potChips={20}
        potOdds={null}
        showPotOdds
        dealFrom={3}
        dealBaseMs={200}
        dealStaggerMs={100}
      />,
    )
    const cards = [...container.querySelectorAll('[data-face="up"]')]
    expect(cards.map((c) => c.getAttribute('data-dealing'))).toEqual([
      null,
      null,
      null,
      'true',
      'true',
    ])
    expect((cards[4] as HTMLElement).style.animationDelay).toBe('300ms')
  })

  it('does not animate without dealFrom', () => {
    const { container } = render(
      <TableCentre board={['Ah', 'Kd', '7c']} potChips={20} potOdds={null} showPotOdds />,
    )
    expect(container.querySelector('[data-dealing]')).toBeNull()
  })
})
