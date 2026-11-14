import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Explanation } from '../../api/types'
import { formatEvBb, formatPct } from '../../lib/format'
import { guessLines } from '../../lib/result'
import { attemptFixture, explanationLlmFixture, fixtureNames } from '../../test/fixture'
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

describe('status line and footer', () => {
  const footer = (container: HTMLElement) =>
    container.firstElementChild?.lastElementChild?.textContent
  const llm = explanationLlmFixture()
  const fallback = (f: Explanation['fallback']): Explanation => ({ ...explanation, fallback: f })

  it('shows a status line while the rewrite is pending', () => {
    render(<ExplanationPanel explanation={explanation} pendingModel="llama3.2:3b" />)
    expect(screen.getByRole('status')).toHaveTextContent(
      'Rewriting in plain English with llama3.2:3b…',
    )
  })

  it('has no status line otherwise', () => {
    render(<ExplanationPanel explanation={explanation} />)
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('template: the trainer wrote it', () => {
    const { container } = render(<ExplanationPanel explanation={explanation} llmStatus="ready" />)
    expect(footer(container)).toBe('Written by the trainer from the graded numbers.')
  })

  it('llm: names the model', () => {
    const { container } = render(<ExplanationPanel explanation={llm} llmStatus="ready" />)
    expect(llm.source).toBe('llm')
    expect(footer(container)).toBe(
      `Reworded by ${llm.model}, a local model. Every number in it was checked against the grader's numbers.`,
    )
  })

  it('off: points to the setup', () => {
    const { container } = render(<ExplanationPanel explanation={explanation} llmStatus="off" />)
    expect(footer(container)).toBe(
      'Explanations come from templates. A local model (Ollama) can reword them: see backend/.env.example.',
    )
  })

  // the backend's probe details (explain/ollama.py), each a sentence ending with a full stop
  it.each([
    [
      'Ollama is running but the model llama3.2:3b isn\'t pulled: run "ollama pull llama3.2:3b".',
      "The local model isn't available: Ollama is running but the model llama3.2:3b isn't pulled: run \"ollama pull llama3.2:3b\". Reload the page once it's ready.",
    ],
    [
      "Ollama isn't answering at http://127.0.0.1:11434.",
      "The local model isn't available: Ollama isn't answering at http://127.0.0.1:11434. Reload the page once it's ready.",
    ],
    [
      'Not checked yet.',
      "The local model isn't available: Not checked yet. Reload the page once it's ready.",
    ],
  ])('unavailable: shows the settings detail once stopped (%s)', (detail, text) => {
    const { container } = render(
      <ExplanationPanel explanation={explanation} llmStatus="unavailable" llmDetail={detail} />,
    )
    expect(footer(container)).toBe(text)
  })

  it('unavailable without a detail', () => {
    const { container } = render(
      <ExplanationPanel explanation={explanation} llmStatus="unavailable" />,
    )
    expect(footer(container)).toBe(
      "The local model isn't available. Reload the page once it's ready.",
    )
  })

  it.each([
    [
      'guardrail',
      "The local model's text didn't keep to the grader's numbers and verdict, so the trainer's own text is shown.",
    ],
    ['timeout', "The local model didn't answer in time."],
    ['error', "The local model's answer couldn't be used, so the trainer's own text is shown."],
    ['invalid', "The local model's answer couldn't be used, so the trainer's own text is shown."],
  ] as const)('fallback %s', (f, text) => {
    const { container } = render(<ExplanationPanel explanation={fallback(f)} llmStatus="ready" />)
    expect(footer(container)).toBe(text)
  })

  it('fallback unavailable uses the detail', () => {
    const { container } = render(
      <ExplanationPanel
        explanation={fallback('unavailable')}
        llmDetail="Ollama isn't answering at http://127.0.0.1:11434."
      />,
    )
    expect(footer(container)).toBe(
      "The local model isn't available: Ollama isn't answering at http://127.0.0.1:11434. Reload the page once it's ready.",
    )
  })

  it('a failed request is noted', () => {
    const { container } = render(
      <ExplanationPanel explanation={explanation} llmStatus="ready" requestFailed />,
    )
    expect(footer(container)).toBe(
      "The local model couldn't be reached, so the trainer's own text is shown.",
    )
  })
})
