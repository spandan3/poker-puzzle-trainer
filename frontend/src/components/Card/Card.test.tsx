import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Card } from './Card'

describe('Card', () => {
  it('names a face-up card', () => {
    render(<Card card="Th" />)
    const card = screen.getByRole('img', { name: 'Ten of hearts' })
    expect(card).toHaveAttribute('data-suit', 'h')
  })

  it.each([
    ['As', 'Ace of spades', 's'],
    ['Kd', 'King of diamonds', 'd'],
    ['2c', 'Two of clubs', 'c'],
    ['Qh', 'Queen of hearts', 'h'],
  ])('labels %s and marks its suit', (code, name, suit) => {
    render(<Card card={code} size="lg" />)
    expect(screen.getByRole('img', { name })).toHaveAttribute('data-suit', suit)
  })

  it('prints T as 10', () => {
    render(<Card card="Tc" />)
    expect(screen.getByRole('img', { name: 'Ten of clubs' })).toHaveTextContent('10')
  })

  it('hides the identity of a face-down card', () => {
    render(<Card card={null} faceDown />)
    const card = screen.getByRole('img', { name: 'face-down card' })
    expect(card).not.toHaveAttribute('data-suit')
    expect(card).toHaveAttribute('data-face', 'down')
    expect(card.textContent).toBe('')
  })

  it('never leaks a known card when face down', () => {
    render(<Card card="As" faceDown />)
    const card = screen.getByRole('img', { name: 'face-down card' })
    expect(card.textContent).toBe('')
    for (const attr of ['data-suit', 'data-rank', 'data-card', 'data-colour']) {
      expect(card).not.toHaveAttribute(attr)
    }
    expect(card.outerHTML).not.toContain('As')
    expect(card.outerHTML.toLowerCase()).not.toContain('spade')
  })

  it('renders an empty slot for card={null}', () => {
    const { container } = render(<Card card={null} />)
    const slot = container.querySelector('[data-face="empty"]')
    expect(slot).not.toBeNull()
    expect(slot).not.toHaveAttribute('data-suit')
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('sets a deal delay only when asked', () => {
    render(<Card card="5d" dealDelayMs={240} />)
    expect(screen.getByRole('img', { name: 'Five of diamonds' })).toHaveAttribute(
      'data-dealing',
      'true',
    )
    expect(screen.getByRole('img', { name: 'Five of diamonds' }).style.animationDelay).toBe('240ms')
  })
})
