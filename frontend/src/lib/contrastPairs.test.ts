import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { composite, contrastRatio, resolveTokens } from './contrast'

// The colour claims of the design tokens, as a listed table of text/background and boundary
// pairs. Translucent fills are composited over the surface they sit on.
const css = (name: string) => readFileSync(resolve(import.meta.dirname, '../styles', name), 'utf8')
const tokens = resolveTokens(
  ['tokens.css', 'tokens.answer.css', 'tokens.results.css', 'tokens.ui.css'].map(css),
)
const t = (name: string): string => {
  const v = tokens[name]
  if (v === undefined) throw new Error(`no token ${name}`)
  return v
}
/** A token's colour (alpha included) laid over a surface token. */
const over = (fill: string, surface: string) => composite(t(fill), 1, t(surface))

const SURFACES = ['--color-bg', '--color-panel', '--color-bg-raised', '--color-bg-sunken'] as const

const TEXT_ON_SURFACE: [string, string][] = []
for (const fg of ['--color-text', '--color-text-muted', '--color-text-faint']) {
  for (const bg of SURFACES) TEXT_ON_SURFACE.push([fg, bg])
}
for (const fg of [
  '--color-verdict-best',
  '--color-verdict-fine',
  '--color-verdict-mistake',
  '--color-verdict-blunder',
  '--color-danger',
  '--color-warning',
  '--color-info',
  '--color-accent',
]) {
  TEXT_ON_SURFACE.push([fg, '--color-panel'])
}
TEXT_ON_SURFACE.push(
  // a folded seat's muted name, position and stack on the plate
  ['--color-text-muted', '--color-seat-bg'],
  ['--color-text-muted', '--color-seat-bg-top'],
  ['--color-text-on-felt', '--color-felt-light'],
  ['--color-text-on-felt-muted', '--color-felt-light'],
  ['--answer-submit-text', '--answer-submit-bg'],
  ['--answer-submit-text', '--answer-submit-bg-hover'],
  // (the disabled Submit label is exempt from WCAG 1.4.3: an inactive component)
  ['--answer-intent-selected-text', '--answer-intent-selected-bg'],
  ['--answer-kbd-text', '--answer-control-bg'],
  ['--color-text', '--answer-control-bg'],
  ['--color-text', '--answer-input-bg'],
  ['--color-tooltip-text', '--color-tooltip-bg'],
)

describe('text contrast (4.5:1)', () => {
  it.each(TEXT_ON_SURFACE)('%s on %s', (fg, bg) => {
    expect(contrastRatio(t(fg), t(bg))).toBeGreaterThanOrEqual(4.5)
  })

  it('badge, profile and all-in text on their own fills over the seat plate and the panel', () => {
    for (const surface of ['--color-seat-bg', '--color-seat-bg-top', '--color-panel']) {
      expect(
        contrastRatio(t('--color-badge-text'), over('--color-badge-bg', surface)),
      ).toBeGreaterThanOrEqual(4.5)
      expect(
        contrastRatio(t('--color-profile-text'), over('--color-profile-bg', surface)),
      ).toBeGreaterThanOrEqual(4.5)
      expect(
        contrastRatio(t('--color-allin-text'), over('--color-allin-bg', surface)),
      ).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('verdict colours: as text on the panel and the raised surface, and on a Badge fill over them', () => {
    // verdict Badges (Options "Best", the analysis steps) sit inside panels, never on a seat plate
    for (const v of ['best', 'fine', 'mistake', 'blunder']) {
      for (const surface of ['--color-panel', '--color-bg-raised']) {
        const fg = t(`--color-verdict-${v}`)
        expect(contrastRatio(fg, t(surface))).toBeGreaterThanOrEqual(4.5)
        // the Badge's translucent fill composited over the surface (worst: blunder, 4.91:1)
        expect(contrastRatio(fg, over('--color-badge-bg', surface))).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('selected states: body text on the tint over the control it replaces', () => {
    expect(
      contrastRatio(t('--color-text'), over('--answer-size-selected-bg', '--answer-control-bg')),
    ).toBeGreaterThanOrEqual(4.5)
    expect(
      contrastRatio(t('--color-text'), over('--color-accent-soft', '--color-panel')),
    ).toBeGreaterThanOrEqual(4.5)
    expect(
      contrastRatio(t('--color-text'), over('--color-accent-soft', '--answer-control-bg')),
    ).toBeGreaterThanOrEqual(4.5)
  })

  it('the Progress warm-up band: its label and the chart text on the band', () => {
    const band = over('--color-badge-bg', '--color-panel')
    expect(contrastRatio(t('--color-text-muted'), band)).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(t('--color-text'), band)).toBeGreaterThanOrEqual(4.5)
  })

  it('the bet label and the dealer button text', () => {
    expect(
      contrastRatio(t('--color-bet-text'), over('--color-bet-bg', '--color-felt-light')),
    ).toBeGreaterThanOrEqual(4.5)
    expect(
      contrastRatio(t('--color-dealer-text'), t('--color-dealer-face')),
    ).toBeGreaterThanOrEqual(4.5)
  })
})

describe('control boundaries (3:1)', () => {
  // --answer-control-bg-hover: a hovered secondary Button or Select, and a hovered step button
  it.each([
    ...SURFACES,
    '--answer-control-bg',
    '--answer-control-bg-hover',
    '--answer-input-bg',
    '--color-seat-bg',
  ])('--control-border on %s', (bg) => {
    expect(contrastRatio(t('--control-border'), t(bg))).toBeGreaterThanOrEqual(3)
  })

  it('the selected-state borders on the tint', () => {
    expect(
      contrastRatio(
        t('--answer-size-selected-border'),
        over('--answer-size-selected-bg', '--answer-control-bg'),
      ),
    ).toBeGreaterThanOrEqual(3)
    expect(contrastRatio(t('--color-focus'), t('--color-panel'))).toBeGreaterThanOrEqual(3)
    expect(contrastRatio(t('--color-focus'), t('--color-bg'))).toBeGreaterThanOrEqual(3)
  })
})
