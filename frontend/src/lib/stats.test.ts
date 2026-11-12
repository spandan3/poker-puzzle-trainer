import { afterEach, describe, expect, it, vi } from 'vitest'
import { bb1, chartScale, deltaText, localTimeZone, pct, pts, shortDate } from './stats'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('formatting', () => {
  it('shows errors in percentage points with one decimal', () => {
    expect(pts(0.042)).toBe('4.2 pts')
    expect(pts(0.09288)).toBe('9.3 pts')
    expect(pts(0)).toBe('0.0 pts')
  })

  it('shows shares as whole percentages', () => {
    expect(pct(0.88)).toBe('88%')
    expect(pct(1)).toBe('100%')
  })

  it('shows bb with one decimal', () => {
    expect(bb1(1.5766)).toBe('1.6 bb')
    expect(bb1(140.17)).toBe('140.2 bb')
  })

  it('shortens a date without a time zone', () => {
    expect(shortDate('2026-11-12')).toBe('Nov 12')
    expect(shortDate('2026-01-05')).toBe('Jan 5')
    expect(shortDate('garbage')).toBe('garbage')
  })
})

describe('deltaText', () => {
  it('says better when EV lost fell', () => {
    expect(deltaText(1.2, 1.5)).toBe('0.3 bb better than the 50 before')
  })

  it('says worse when EV lost rose', () => {
    expect(deltaText(2.0, 1.5)).toBe('0.5 bb worse than the 50 before')
  })

  it('says same when the difference rounds to zero (2 decimals, as EV is shown)', () => {
    expect(deltaText(1.5, 1.5)).toBe('same as the 50 before')
    expect(deltaText(1.501, 1.5)).toBe('same as the 50 before')
    expect(deltaText(1.52, 1.5)).toBe('0.02 bb worse than the 50 before')
  })

  it('is null when either side is missing', () => {
    expect(deltaText(null, 1.5)).toBeNull()
    expect(deltaText(1.5, null)).toBeNull()
  })
})

describe('localTimeZone', () => {
  it('returns the browser zone', () => {
    vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(
      () => ({ resolvedOptions: () => ({ timeZone: 'Europe/London' }) }) as Intl.DateTimeFormat,
    )
    expect(localTimeZone()).toBe('Europe/London')
  })

  it('falls back to UTC when Intl throws or gives nothing', () => {
    const spy = vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(() => {
      throw new Error('no intl')
    })
    expect(localTimeZone()).toBe('UTC')
    spy.mockImplementation(
      () =>
        ({ resolvedOptions: () => ({ timeZone: undefined }) }) as unknown as Intl.DateTimeFormat,
    )
    expect(localTimeZone()).toBe('UTC')
  })
})

describe('chartScale', () => {
  it('rounds the top up to a nice number with ticks from zero', () => {
    expect(chartScale(3.2)).toEqual({ max: 4, step: 1, ticks: [0, 1, 2, 3, 4] })
    expect(chartScale(14)).toEqual({ max: 15, step: 5, ticks: [0, 5, 10, 15] })
    expect(chartScale(0.42).ticks[0]).toBe(0)
  })

  it('never ends below the data', () => {
    for (const max of [0.01, 0.9, 1, 7, 10, 23.4, 99, 140.2, 1234]) {
      const scale = chartScale(max)
      expect(scale.max).toBeGreaterThanOrEqual(max)
      expect(scale.ticks.length).toBeGreaterThanOrEqual(3)
      expect(scale.ticks.length).toBeLessThanOrEqual(7)
    }
  })

  it('has a unit scale for no data', () => {
    expect(chartScale(0).max).toBe(1)
    expect(chartScale(-3).max).toBe(1)
  })
})
