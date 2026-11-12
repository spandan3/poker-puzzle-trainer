import { describe, expect, it } from 'vitest'
import {
  bbLabel,
  bbToChips,
  chipsToBb,
  formatBb,
  formatDetail,
  formatEvBb,
  formatPct,
} from './format'

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

describe('formatEvBb', () => {
  it('uses two decimals without trailing zeros', () => {
    expect(formatEvBb(2.25)).toBe('2.25 bb')
    expect(formatEvBb(5)).toBe('5 bb')
    expect(formatEvBb(2.3191875)).toBe('2.32 bb')
    expect(formatEvBb(-7.8)).toBe('−7.8 bb')
  })
})

describe('bbLabel', () => {
  it('shows chips in bb and Hero as you', () => {
    expect(bbLabel('Villain raises to 40 — Hero folds')).toBe('Villain raises to 20 bb — you fold')
    expect(bbLabel('Villain bets 14 — Hero calls')).toBe('Villain bets 7 bb — you call')
    expect(bbLabel('Villain bets 14 — Hero folds')).toBe('Villain bets 7 bb — you fold')
    expect(bbLabel('Villain raises to 9 — Hero calls')).toBe('Villain raises to 4.5 bb — you call')
  })

  it('leaves labels without chips alone', () => {
    expect(bbLabel('Villain calls')).toBe('Villain calls')
    expect(bbLabel('Villain folds')).toBe('Villain folds')
  })
})
