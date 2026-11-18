import { describe, expect, it } from 'vitest'
import {
  bb2,
  bbLabel,
  bbToChips,
  chipsToBb,
  formatBb,
  formatDetail,
  formatEvBb,
  formatPct,
  MINUS,
  nowrapUnits,
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

describe('nowrapUnits', () => {
  it('puts a no-break space before "bb"', () => {
    expect(nowrapUnits('opens to 2.5 bb')).toBe('opens to 2.5\u00a0bb')
    expect(nowrapUnits('raises to 7 bb, then 9 bb')).toBe('raises to 7\u00a0bb, then 9\u00a0bb')
  })

  it('leaves text without "bb" as it is', () => {
    expect(nowrapUnits('checks')).toBe('checks')
    expect(nowrapUnits('a bbq night')).toBe('a bbq night')
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

  it('leaves pot fractions and multiples alone, but converts custom chip sizes', () => {
    expect(bbLabel('bet 33%')).toBe('bet 33%')
    expect(bbLabel('bet 100%')).toBe('bet 100%')
    expect(bbLabel('raise 2.5x')).toBe('raise 2.5x')
    expect(bbLabel('bet 14')).toBe('bet 7 bb')
    expect(bbLabel('raise to 14')).toBe('raise to 7 bb')
  })
})

describe('MINUS', () => {
  it('is U+2212, and the EV formatters use it', () => {
    expect(MINUS).toBe('\u2212')
    expect(formatEvBb(-1.5)).toBe(`${MINUS}1.5 bb`)
    expect(bb2(-0.7)).toBe(`${MINUS}0.70 bb`)
  })
})

describe('bb2', () => {
  it('keeps two decimals, so a column lines up', () => {
    expect(bb2(0)).toBe('0.00 bb')
    expect(bb2(0.7)).toBe('0.70 bb')
    expect(bb2(27.65)).toBe('27.65 bb')
    expect(bb2(1.256)).toBe('1.26 bb')
  })

  it('never shows a negative zero', () => {
    expect(bb2(-0.001)).toBe('0.00 bb')
  })
})
