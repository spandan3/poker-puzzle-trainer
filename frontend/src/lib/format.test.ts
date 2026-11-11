import { describe, expect, it } from 'vitest'
import { bbToChips, chipsToBb, formatBb, formatDetail, formatPct } from './format'

describe('formatBb', () => {
  it('shows big blinds with at most one decimal', () => {
    expect(formatBb(5)).toBe('2.5 bb')
    expect(formatBb(200)).toBe('100 bb')
    expect(formatBb(1)).toBe('0.5 bb')
    expect(formatBb(0)).toBe('0 bb')
    expect(formatBb(195)).toBe('97.5 bb')
  })

  it('never shows float noise or a trailing zero', () => {
    for (let chips = 0; chips <= 400; chips++) {
      const text = formatBb(chips)
      expect(text).toMatch(/^\d+(\.5)? bb$/)
    }
  })
})

describe('bb conversion', () => {
  it('converts to the nearest chip', () => {
    expect(bbToChips(2.5)).toBe(5)
    expect(bbToChips(0.5)).toBe(1)
    expect(bbToChips(100)).toBe(200)
    expect(bbToChips(2.26)).toBe(5)
  })

  it('round-trips 0..400 chips', () => {
    for (let chips = 0; chips <= 400; chips++) {
      expect(bbToChips(chipsToBb(chips))).toBe(chips)
    }
  })
})

describe('formatPct', () => {
  it('formats a fraction as a percentage', () => {
    expect(formatPct(0.256)).toBe('26%')
    expect(formatPct(0.256, 1)).toBe('25.6%')
    expect(formatPct(1)).toBe('100%')
    expect(formatPct(0)).toBe('0%')
  })
})

describe('formatDetail', () => {
  it('returns a string detail as is', () => {
    expect(formatDetail('puzzle already answered')).toBe('puzzle already answered')
  })

  it('joins the messages of a validation array', () => {
    const detail = [
      { loc: ['body', 'equity_guess'], msg: 'Input should be less than or equal to 1', type: 'x' },
      { loc: ['body', 'option'], msg: 'Field required', type: 'y' },
    ]
    expect(formatDetail(detail)).toBe('Input should be less than or equal to 1; Field required')
  })

  it('falls back for anything else', () => {
    expect(formatDetail(undefined)).toBe('Something went wrong')
    expect(formatDetail({ foo: 1 })).toBe('Something went wrong')
    expect(formatDetail([])).toBe('Something went wrong')
  })
})
