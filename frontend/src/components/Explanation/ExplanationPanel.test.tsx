import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Explanation } from '../../api/types'
import { formatEvBb, formatPct } from '../../lib/format'
import { guessLines } from '../../lib/result'
import { attemptFixture, fixtureNames } from '../../test/fixture'
import { ExplanationPanel } from './ExplanationPanel'

const explanation: Explanation = {
  source: 'template',
  model: null,
  fallback: null,
  headline: 'Best play: call.',
  sections: [
    { id: 'verdict', title: 'Verdict', paragraphs: ['First <b>not bold</b>.', 'Second.'] },
    { id: 'hand', title: 'Your hand', paragraphs: ['Third.'] },
    { id: 'villain', title: 'Villain', paragraphs: ['Fourth.'] },
  ],
}

describe('ExplanationPanel', () => {
  it('renders the headline, the sections and their paragraphs in order', () => {
    const { container } = render(<ExplanationPanel explanation={explanation} />)
    expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
      'Verdict',
      'Your hand',
      'Villain',
    ])
    const paragraphs = Array.from(container.querySelectorAll('p')).map((p) => p.textContent)
    expect(paragraphs).toEqual([
      'Best play: call.',
      'First <b>not bold</b>.',
      'Second.',
      'Third.',
      'Fourth.',
      'Written by the trainer from the graded numbers.',
    ])
  })

  it('shows markup in the text literally', () => {
    const { container } = render(<ExplanationPanel explanation={explanation} />)
    expect(container.querySelector('b')).toBeNull()
  })
})

/** a RegExp matching `value` only as a whole number ("9.7%" must not match inside "19.7%") */
const standalone = (value: string) =>
  new RegExp(`(?<![\\d.])${value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\d])`)

describe('Why text and the summary agree (every attempt fixture)', () => {
  const names = fixtureNames().filter((n) => n.startsWith('attempt_'))
  it('has attempt fixtures', () => expect(names.length).toBeGreaterThan(0))

  for (const name of names) {
    it(`${name}: equity, EV lost, pot odds and fold frequencies appear verbatim`, () => {
      const result = attemptFixture(name.replace(/^attempt_/, ''))
      const { container } = render(<ExplanationPanel explanation={result.explanation} />)
      const text = container.textContent ?? ''
      const equity = guessLines(result).find((l) => l.label === 'Equity')!.actual
      expect(text).toMatch(standalone(equity))
      if (result.grade.ev_loss_bb >= 0.005) {
        expect(text).toMatch(standalone(formatEvBb(result.grade.ev_loss_bb)))
      }
      // pot odds: stated when facing a bet (a call option exists), as the Maths tab shows them
      if (result.grade.pot_odds !== null && result.options.some((o) => o.kind === 'call')) {
        expect(text).toMatch(standalone(formatPct(result.grade.pot_odds, 1)))
      }
      // fold frequency: stated for the best and chosen bet/raise unless Villain never continues
      for (const o of result.options) {
        const stated = o.is_best || o.is_chosen
        const continues = o.equity_vs_continue !== null || o.ahead_vs_continue !== null
        if ((o.kind === 'bet' || o.kind === 'raise') && stated && continues) {
          if (o.fold_freq !== null) expect(text).toMatch(standalone(formatPct(o.fold_freq)))
        }
      }
    })
  }
})

describe('suits', () => {
  it('asks for the text style of a suit, never the emoji one', () => {
    const e: Explanation = {
      ...explanation,
      headline: 'A♥ K♠',
      sections: [{ id: 'hand', title: 'The hand', paragraphs: ['Q♥\uFE0F J♦ T♥.'] }],
    }
    const { container } = render(<ExplanationPanel explanation={e} />)
    const text = container.textContent ?? ''
    expect(text).toContain('A♥\uFE0E K♠\uFE0E')
    expect(text).toContain('Q♥\uFE0E J♦\uFE0E T♥\uFE0E.')
    expect(text).not.toContain('\uFE0F')
  })
})
