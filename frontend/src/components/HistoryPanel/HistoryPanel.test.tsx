import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { answerEntry } from '../../lib/result'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
import { HistoryPanel } from './HistoryPanel'

describe('HistoryPanel', () => {
  it('has a region heading and one heading and list per street', () => {
    render(<HistoryPanel view={puzzleFixture('history_3bet_and_all_in')} />)
    expect(screen.getByRole('heading', { name: 'Action' })).toBeInTheDocument()
    const headings = screen.getAllByRole('heading', { level: 3 })
    expect(headings.map((h) => h.textContent)).toEqual([
      expect.stringContaining('Pre-flop'),
      expect.stringContaining('Flop'),
      expect.stringContaining('Turn'),
    ])
    expect(screen.getAllByRole('list')).toHaveLength(3)
  })

  it('lists entries in bb with actor and position', () => {
    render(<HistoryPanel view={puzzleFixture('history_3bet_and_all_in')} />)
    const preflop = screen.getByRole('list', { name: 'Pre-flop actions' })
    const items = within(preflop).getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(items[0]).toHaveTextContent('Hero')
    expect(items[0]).toHaveTextContent('opens to 2.5 bb')
    expect(items[0]).toHaveAttribute('data-actor', 'hero')
    expect(items[1]).toHaveTextContent('Villain')
    expect(items[1]).toHaveTextContent('3-bets to 7.5 bb')
    expect(items[1]).toHaveAttribute('data-actor', 'villain')
    const turn = within(screen.getByRole('list', { name: 'Turn actions' })).getAllByRole('listitem')
    expect(turn.at(-1)).toHaveTextContent('all-in to 87.5 bb')
  })

  it('shows positions', () => {
    const view = puzzleFixture('flop_unopened')
    render(<HistoryPanel view={view} />)
    const items = within(screen.getByRole('list', { name: 'Pre-flop actions' })).getAllByRole(
      'listitem',
    )
    expect(items[0]).toHaveTextContent(view.villain_position)
    expect(items[1]).toHaveTextContent(view.hero_position)
  })

  it('shows the board cards that arrived on each street', () => {
    render(<HistoryPanel view={puzzleFixture('history_3bet_and_all_in')} />)
    const flop = screen.getByRole('region', { name: 'Flop' })
    expect(
      within(flop)
        .getAllByRole('img')
        .map((c) => c.getAttribute('aria-label')),
    ).toEqual(['Nine of diamonds', 'Jack of diamonds', 'Two of clubs'])
    const turn = screen.getByRole('region', { name: 'Turn' })
    expect(within(turn).getAllByRole('img')).toHaveLength(1)
    const pre = screen.getByRole('region', { name: 'Pre-flop' })
    expect(within(pre).queryAllByRole('img')).toHaveLength(0)
  })

  it('shows an empty decision street with Hero to act', () => {
    render(<HistoryPanel view={puzzleFixture('flop_unopened')} />)
    const flop = screen.getByRole('region', { name: 'Flop' })
    expect(within(flop).queryByRole('list')).not.toBeInTheDocument()
    expect(within(flop).getByText('No action yet')).toBeInTheDocument()
    expect(screen.getAllByText('Hero to act')).toHaveLength(1)
    expect(flop).toHaveTextContent('Hero to act')
  })

  it('uses unique ids when two panels are rendered together', () => {
    const { container } = render(
      <>
        <HistoryPanel view={puzzleFixture('flop_unopened')} />
        <HistoryPanel view={puzzleFixture('flop_unopened')} />
      </>,
    )
    const ids = [...container.querySelectorAll('[id]')].map((el) => el.id)
    expect(ids.length).toBeGreaterThan(2)
    expect(new Set(ids).size).toBe(ids.length)
    expect(screen.getAllByRole('region', { name: 'Flop' })).toHaveLength(2)
  })

  it('never reveals anything beyond the board', () => {
    const view = puzzleFixture('flop_unopened')
    const { container } = render(<HistoryPanel view={view} />)
    expect(container.querySelectorAll('[data-face="up"]')).toHaveLength(view.board.length)
  })

  it("after a submit, shows Hero's answer instead of Hero to act", () => {
    const view = puzzleFixture('flop_unopened')
    render(<HistoryPanel view={view} answer={answerEntry(view, attemptFixture('bet'))} />)
    expect(screen.queryByText('Hero to act')).toBeNull()
    expect(screen.getByText('bets 1.5 bb (30% pot)')).toBeVisible()
    expect(screen.getByText('your answer')).toBeVisible()
  })
})
