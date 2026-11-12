import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { attemptFixture } from '../../test/fixture'
import { ResultSummary } from './ResultSummary'

describe('ResultSummary', () => {
  it('shows the verdict, the guesses and the note (Villain and the run-out are in the Hand tab)', () => {
    const result = attemptFixture('bet')
    render(<ResultSummary result={result} onNext={() => {}} onDetails={() => {}} shortcutsOn />)
    const status = screen.getByRole('region', { name: 'Result' })
    expect(status).toHaveTextContent('Best')
    expect(status).toHaveTextContent('You: Bet 33% · the top play')
    expect(screen.getByRole('region', { name: 'Result' })).toHaveAttribute('data-verdict', 'best')
    expect(screen.getByText(/you 45% · actual 46.4%/)).toBeVisible()
    expect(screen.getByText(/you 50% · actual 47.0%/)).toBeVisible()
    expect(screen.queryByText('LAG')).toBeNull()
    expect(screen.queryByText(/Hero wins/)).toBeNull()
    expect(screen.getByText(result.judged_on_range_note)).toBeVisible()
    expect(screen.getByText(result.grade.intent_flag!)).toBeVisible()
  })

  it('colour-codes each verdict', () => {
    const result = attemptFixture('fold')
    render(<ResultSummary result={result} onNext={() => {}} onDetails={() => {}} shortcutsOn />)
    expect(screen.getByText('Mistake')).toHaveAttribute('data-verdict', 'mistake')
  })

  it('Next calls onNext, shows N, and does nothing while loading', async () => {
    const user = userEvent.setup()
    const onNext = vi.fn()
    const { rerender } = render(
      <ResultSummary
        result={attemptFixture('bet')}
        onNext={onNext}
        onDetails={() => {}}
        shortcutsOn
      />,
    )
    const next = screen.getByRole('button', { name: /Next puzzle/ })
    expect(next).toHaveAttribute('aria-keyshortcuts', 'N')
    expect(next.querySelector('kbd')).toHaveTextContent('N')
    await user.click(next)
    expect(onNext).toHaveBeenCalledTimes(1)
    rerender(
      <ResultSummary
        result={attemptFixture('bet')}
        onNext={onNext}
        onDetails={() => {}}
        shortcutsOn
        loading
      />,
    )
    await user.click(screen.getByRole('button', { name: /Dealing/ }))
    expect(onNext).toHaveBeenCalledTimes(1)
  })

  it('no key hint with shortcuts off', () => {
    render(
      <ResultSummary
        result={attemptFixture('bet')}
        onNext={() => {}}
        onDetails={() => {}}
        shortcutsOn={false}
      />,
    )
    const next = screen.getByRole('button', { name: /Next puzzle/ })
    expect(next).not.toHaveAttribute('aria-keyshortcuts')
    expect(next.querySelector('kbd')).toBeNull()
  })

  it('shows the intent flag only when there is one', () => {
    const result = attemptFixture('fold')
    const { rerender } = render(
      <ResultSummary
        result={{ ...result, grade: { ...result.grade, intent_flag: null } }}
        onNext={() => {}}
        onDetails={() => {}}
        shortcutsOn
      />,
    )
    expect(screen.queryByText(/You labelled this/)).toBeNull()
    const flag = 'You labelled this a bluff, but it is not.'
    rerender(
      <ResultSummary
        result={{ ...result, grade: { ...result.grade, intent_flag: flag } }}
        onNext={() => {}}
        onDetails={() => {}}
        shortcutsOn
      />,
    )
    expect(screen.getByText(flag)).toBeVisible()
  })

  it('Details calls onDetails', async () => {
    const user = userEvent.setup()
    const onDetails = vi.fn()
    render(
      <ResultSummary
        result={attemptFixture('bet')}
        onNext={() => {}}
        onDetails={onDetails}
        shortcutsOn
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Details' }))
    expect(onDetails).toHaveBeenCalledTimes(1)
  })
})
