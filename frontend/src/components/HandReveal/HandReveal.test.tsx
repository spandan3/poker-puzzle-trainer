import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { cardName } from '../../lib/cards'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
import { HandReveal } from './HandReveal'

describe('HandReveal', () => {
  it('shows Villain, the profile, the run-out, the showdown, the note and the simplifications', () => {
    const view = puzzleFixture('flop_unopened')
    const result = attemptFixture('bet')
    render(<HandReveal view={view} result={result} />)
    const villain = screen.getByRole('group', { name: "Villain's hand" })
    for (const c of result.reveal.villain_cards) {
      expect(within(villain).getByRole('img', { name: cardName(c) })).toBeVisible()
    }
    expect(screen.getByText(result.reveal.profile.label)).toBeVisible()
    expect(screen.getByText(result.reveal.profile.description)).toBeVisible()
    const runout = screen.getByRole('group', { name: 'Run-out' })
    expect(within(runout).getAllByRole('img')).toHaveLength(5)
    expect(screen.getByText('Hero wins: Pair vs Pair')).toBeVisible()
    expect(screen.getByText(result.judged_on_range_note)).toBeVisible()
    const list = screen.getByRole('list', { name: 'Simplifications' })
    const items = within(list).getAllByRole('listitem')
    expect(items.map((i) => i.textContent)).toEqual(result.simplifications.map((s) => s.text))
  })

  it('after a fold: only the decision board and no showdown', () => {
    const view = puzzleFixture('facing_postflop_raise')
    const result = attemptFixture('fold')
    render(<HandReveal view={view} result={result} />)
    const board = screen.getByRole('group', { name: 'Board at the decision' })
    expect(within(board).getAllByRole('img')).toHaveLength(view.board.length)
    expect(screen.queryByRole('group', { name: 'Run-out' })).toBeNull()
    expect(screen.getByText("You folded, so there's no showdown.")).toBeVisible()
    expect(screen.getByText(result.reveal.profile.label)).toBeVisible()
  })
})
