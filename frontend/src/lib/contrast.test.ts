import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { composite, contrastRatio, parseColor, resolveTokens } from './contrast'

// Vitest turns `?raw` CSS imports into empty strings, so the real files are read from disk.
const css = (name: string) => readFileSync(resolve(import.meta.dirname, '../styles', name), 'utf8')
const tokens = resolveTokens(
  ['tokens.css', 'tokens.answer.css', 'tokens.results.css', 'tokens.ui.css'].map(css),
)
const t = (name: string): string => {
  const v = tokens[name]
  if (v === undefined) throw new Error(`no token ${name}`)
  return v
}

describe('parseColor', () => {
  it('reads hex and rgb forms', () => {
    expect(parseColor('#abc')).toEqual({ r: 170, g: 187, b: 204, a: 1 })
    expect(parseColor('#aabbcc')).toEqual({ r: 170, g: 187, b: 204, a: 1 })
    expect(parseColor('rgb(61 220 151 / 16%)')).toEqual({ r: 61, g: 220, b: 151, a: 0.16 })
    expect(parseColor('rgb(1, 2, 3)')).toEqual({ r: 1, g: 2, b: 3, a: 1 })
  })
  it('rejects what it cannot read', () => {
    expect(() => parseColor('banana')).toThrow()
  })
})

describe('resolveTokens', () => {
  it('resolves aliases', () => {
    expect(t('--answer-fill')).toBe('#3ddc97')
    expect(t('--text-page-title')).toBe('1.625rem')
  })
  it('throws a named error on a gradient', () => {
    expect(() => tokens['--answer-bg']).toThrow(/--answer-bg/)
  })
})

describe('contrastRatio and composite', () => {
  it('matches the WCAG extremes', () => {
    expect(contrastRatio('#000', '#fff')).toBe(21)
    expect(contrastRatio('#777', '#777')).toBe(1)
  })
  it('matches a hand-computed value for text on the page background', () => {
    // L(#e8edf3) = 0.842 and L(#0c0f14) = 0.0047, so (0.842 + 0.05) / (0.0047 + 0.05) = 16.31
    expect(contrastRatio(t('--color-text'), t('--color-bg'))).toBeCloseTo(16.305, 2)
  })
  it('matches a hand-computed value on a dark background (the linear branch)', () => {
    // #080a0e has channels below 10/255, where the sRGB curve is linear
    expect(contrastRatio(t('--color-text'), '#080a0e')).toBeCloseTo(16.83, 2)
  })
  it('refuses a translucent colour', () => {
    expect(() => contrastRatio('rgb(255 255 255 / 8%)', '#000')).toThrow(/composite/)
    expect(() => composite('#fff', 0.5, 'rgb(0 0 0 / 50%)')).toThrow(/opaque/)
  })
  it('uses the foreground colour’s own alpha when blending', () => {
    expect(composite('rgb(255 255 255 / 50%)', 1, '#000000')).toBe('#808080')
    expect(composite('rgb(255 255 255 / 50%)', 0.5, '#000000')).toBe('#404040')
  })
  it('blends over a background', () => {
    expect(composite('#ffffff', 0.5, '#000000')).toBe('#808080')
  })
})

describe('control border', () => {
  it.each(['--answer-control-bg', '--color-panel', '--color-bg-raised', '--color-bg'])(
    'is at least 3:1 on %s',
    (bg) => {
      expect(contrastRatio(t('--control-border'), t(bg))).toBeGreaterThanOrEqual(3)
    },
  )
})
