import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Explanation } from '../../api/types'
import { formatEvBb } from '../../lib/format'
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

describe('Why text and the summary agree (every attempt fixture)', () => {
  const names = fixtureNames().filter((n) => n.startsWith('attempt_'))
  it('has attempt fixtures', () => expect(names.length).toBeGreaterThan(0))

  for (const name of names) {
    it(`${name}: equity and EV lost appear verbatim`, () => {
      const result = attemptFixture(name.replace(/^attempt_/, ''))
      const { container } = render(<ExplanationPanel explanation={result.explanation} />)
      const text = container.textContent ?? ''
      const equity = guessLines(result).find((l) => l.label === 'Equity')!.actual
      expect(text).toContain(equity)
      if (result.grade.ev_loss_bb >= 0.005) {
        expect(text).toContain(formatEvBb(result.grade.ev_loss_bb))
      }
    })
  }
})
