import { describe, expect, it } from 'vitest'
import { cardName, parseCard, rankGlyph, suitGlyph } from './cards'

const RANKS = '23456789TJQKA'
const RANK_NAMES = [
  'Two',
  'Three',
  'Four',
  'Five',
  'Six',
  'Seven',
  'Eight',
  'Nine',
  'Ten',
  'Jack',
  'Queen',
  'King',
  'Ace',
]
const SUITS = { h: 'hearts', d: 'diamonds', c: 'clubs', s: 'spades' } as const

describe('cards', () => {
  it('parses every card', () => {
    for (const r of RANKS) {
      for (const s of Object.keys(SUITS)) {
        expect(parseCard(r + s)).toEqual({ rank: r, suit: s })
      }
    }
  })

  it('names every card', () => {
    expect(cardName('Th')).toBe('Ten of hearts')
    expect(cardName('Ac')).toBe('Ace of clubs')
    RANKS.split('').forEach((r, i) => {
      for (const [s, name] of Object.entries(SUITS)) {
        expect(cardName(r + s)).toBe(`${RANK_NAMES[i]} of ${name}`)
      }
    })
  })

  it('shows T as 10', () => {
    expect(rankGlyph('T')).toBe('10')
    expect(rankGlyph('K')).toBe('K')
    expect(rankGlyph('7')).toBe('7')
  })

  it('has a distinct glyph per suit', () => {
    const glyphs = ['h', 'd', 'c', 's'].map((s) => suitGlyph(s as 'h'))
    expect(new Set(glyphs).size).toBe(4)
    expect(suitGlyph('h')).toBe('♥')
    expect(suitGlyph('s')).toBe('♠')
  })

  it('rejects malformed cards', () => {
    expect(() => parseCard('Xh')).toThrow()
    expect(() => parseCard('A')).toThrow()
    expect(() => parseCard('Ahh')).toThrow()
    expect(() => parseCard('Ax')).toThrow()
  })
})
