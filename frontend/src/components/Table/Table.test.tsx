import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SEAT_SLOTS, seatsFromView, type SeatInfo } from '../../lib/seats'
import { puzzleFixture } from '../../test/fixture'
import { Table } from './Table'

function slotsOf(container: HTMLElement): string[] {
  return [...container.querySelectorAll('[data-slot]')].map((el) => el.getAttribute('data-slot')!)
}

describe('Table', () => {
  it('places a heads-up puzzle at bottom and top, with the centre', () => {
    const seats = seatsFromView(puzzleFixture('preflop_bb_facing_open'), { showProfile: true })
    const { container } = render(<Table seats={seats} centre={<p>Pot 3.5 bb</p>} />)
    expect(slotsOf(container)).toEqual(['bottom', 'top'])
    expect(screen.getByRole('group', { name: 'Hero, BB' })).toHaveAttribute('data-slot', 'bottom')
    expect(screen.getByRole('group', { name: 'Villain, BTN' })).toHaveAttribute('data-slot', 'top')
    expect(screen.getByText('Pot 3.5 bb')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'King of clubs' })).toBeInTheDocument()
    expect(screen.getAllByRole('img', { name: 'face-down card' })).toHaveLength(2)
  })

  it('lays out five seats in distinct slots', () => {
    const slots = SEAT_SLOTS.filter((s) => s !== 'top')
    const seats: SeatInfo[] = slots.map((slot, i) => ({
      slot,
      name: i === 0 ? 'Hero' : `Player ${i + 1}`,
      position: ['BTN', 'SB', 'BB', 'UTG', 'CO'][i]!,
      stackChips: 200 - i * 10,
      betChips: i,
      isHero: i === 0,
      isButton: i === 0,
      cards: i === 0 ? ['Ah', 'Kh'] : [null, null],
      faceDown: i !== 0,
      showProfile: false,
    }))
    const { container } = render(<Table seats={seats} centre={null} />)
    const found = slotsOf(container)
    expect(found).toHaveLength(5)
    expect(new Set(found).size).toBe(5)
    expect(found.sort()).toEqual([...slots].sort())
  })
})
