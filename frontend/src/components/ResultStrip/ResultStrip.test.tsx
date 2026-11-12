import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { attemptFixture } from '../../test/fixture'
import { ResultStrip } from './ResultStrip'

describe('ResultStrip', () => {
  it('shows the verdict in a live region, the guesses, the profile and the note', () => {
    const result = attemptFixture('bet')
    render(<ResultStrip result={result} onNext={() => {}} shortcutsOn />)
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('Best')
    expect(status).toHaveTextContent('You: Bet 33% · the top play')
    expect(screen.getByRole('region', { name: 'Result' })).toHaveAttribute('data-verdict', 'best')
    expect(screen.getByText(/you 45% · actual 46.4%/)).toBeVisible()
    expect(screen.getByText(/you 50% · actual 47.0%/)).toBeVisible()
    expect(screen.getByText('LAG')).toBeVisible()
    expect(screen.getByText(result.judged_on_range_note)).toBeVisible()
    expect(screen.getByText(result.grade.intent_flag!)).toBeVisible()
  })

  it('colour-codes each verdict', () => {
    const result = attemptFixture('fold')
    render(<ResultStrip result={result} onNext={() => {}} shortcutsOn />)
    expect(screen.getByText('Mistake')).toHaveAttribute('data-verdict', 'mistake')
  })

  it('Next calls onNext, shows N, and does nothing while loading', async () => {
    const user = userEvent.setup()
    const onNext = vi.fn()
    const { rerender } = render(
      <ResultStrip result={attemptFixture('bet')} onNext={onNext} shortcutsOn />,
    )
    const next = screen.getByRole('button', { name: /Next puzzle/ })
    expect(next).toHaveAttribute('aria-keyshortcuts', 'N')
    expect(next.querySelector('kbd')).toHaveTextContent('N')
    await user.click(next)
    expect(onNext).toHaveBeenCalledTimes(1)
    rerender(<ResultStrip result={attemptFixture('bet')} onNext={onNext} shortcutsOn loading />)
    await user.click(screen.getByRole('button', { name: /Dealing/ }))
    expect(onNext).toHaveBeenCalledTimes(1)
  })

  it('no key hint with shortcuts off', () => {
    render(<ResultStrip result={attemptFixture('bet')} onNext={() => {}} shortcutsOn={false} />)
    const next = screen.getByRole('button', { name: /Next puzzle/ })
    expect(next).not.toHaveAttribute('aria-keyshortcuts')
    expect(next.querySelector('kbd')).toBeNull()
  })
})
