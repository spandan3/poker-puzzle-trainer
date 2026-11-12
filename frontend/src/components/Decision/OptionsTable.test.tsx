import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { decisionFromAttempt } from '../../lib/decision'
import { formatEvBb } from '../../lib/format'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
import { neverContinuesAttempt } from '../../test/synthetic'
import { OptionsTable } from './OptionsTable'

const flop = puzzleFixture('flop_unopened')

function renderTable(name: 'bet' | 'custom' | 'fold' | 'never') {
  const [view, result] =
    name === 'never'
      ? [flop, neverContinuesAttempt()]
      : name === 'custom'
        ? [puzzleFixture('custom_allowed'), attemptFixture('custom')]
        : name === 'fold'
          ? [puzzleFixture('facing_postflop_raise'), attemptFixture('fold')]
          : [flop, attemptFixture('bet')]
  const decision = decisionFromAttempt(view, result)
  render(<OptionsTable decision={decision} />)
  return decision
}

const rowOf = (name: RegExp | string) => screen.getByRole('row', { name })
const cells = (row: HTMLElement) => within(row).getAllByRole('cell')

describe('OptionsTable', () => {
  it('has one row per option, best EV first', () => {
    const d = renderTable('bet')
    expect(screen.getAllByRole('row')).toHaveLength(d.options.length + 1)
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Option',
      'Size',
      'EV',
      'vs best',
      'Villain folds',
      'Equity when called',
    ])
    const first = screen.getAllByRole('row')[1]!
    expect(within(first).getByRole('rowheader')).toHaveTextContent('Bet 33%')
  })

  it('puts Best and You on the same row when they are the same option', () => {
    renderTable('bet')
    const row = rowOf(/^Bet 33%/)
    expect(within(row).getByText('Best')).toBeVisible()
    expect(within(row).getByText('You')).toBeVisible()
    expect(screen.getAllByText('Best')).toHaveLength(1)
    expect(screen.getAllByText('You')).toHaveLength(1)
  })

  it('puts Best and You on different rows when they differ', () => {
    renderTable('fold')
    expect(within(rowOf(/^Call/)).getByText('Best')).toBeVisible()
    expect(within(rowOf(/^Call/)).queryByText('You')).toBeNull()
    expect(within(rowOf(/^Fold/)).getByText('You')).toBeVisible()
    expect(within(rowOf(/^Fold/)).queryByText('Best')).toBeNull()
  })

  it('shows the API EV in bb, and the loss against the best option', () => {
    const d = renderTable('bet')
    const evCells = screen
      .getAllByRole('row')
      .slice(1)
      .map((row) => cells(row)[1]!.textContent)
    expect(evCells).toEqual(
      [...d.options].sort((x, y) => y.ev_bb - x.ev_bb).map((o) => formatEvBb(o.ev_bb)),
    )
    const best = d.options.find((o) => o.is_best)!
    const check = d.options.find((o) => o.kind === 'check')!
    expect(cells(rowOf(/^Check/))[2]).toHaveTextContent(`−${formatEvBb(best.ev_bb - check.ev_bb)}`)
    expect(cells(rowOf(/^Bet 33%/))[2]).toHaveTextContent('')
    expect(cells(rowOf(/^Bet 33%/))[2]).toBeEmptyDOMElement()
    expect(cells(rowOf(/^Bet 33%/))[1]).toHaveTextContent(formatEvBb(best.ev_bb))
  })

  it('shows a size in bb and the share of the pot', () => {
    renderTable('bet')
    expect(cells(rowOf(/^Bet 33%/))[0]).toHaveTextContent('1.5 bb · 30% pot')
  })

  it('shows a dash when Villain never gets to continue or fold', () => {
    renderTable('bet')
    const check = cells(rowOf(/^Check/))
    expect(check[3]).toHaveTextContent('—')
    expect(check[4]).toHaveTextContent('—')
  })

  it('shows no NaN and a dash for equity when Villain never continues', () => {
    renderTable('never')
    const row = rowOf(/^Bet 33%/)
    expect(cells(row)[3]).toHaveTextContent('100%')
    expect(cells(row)[4]).toHaveTextContent('—')
    expect(cells(row)[1]).toHaveTextContent('5 bb')
    expect(document.body.textContent).not.toMatch(/NaN|undefined|Infinity/)
  })

  it('shows a custom size as the You row with a bb label, and +x when it beats the best', () => {
    const d = renderTable('custom')
    const custom = d.options[d.options.length - 1]!
    expect(custom.is_chosen).toBe(true)
    const row = rowOf(/^Bet 1 bb/)
    expect(within(row).getByText('You')).toBeVisible()
    expect(within(row).queryByText('Best')).toBeNull()
    expect(screen.queryByText('bet 2')).toBeNull()
    const best = d.options.find((o) => o.is_best)!
    expect(custom.ev_bb).toBeGreaterThan(best.ev_bb)
    expect(cells(row)[2]).toHaveTextContent(`+${formatEvBb(custom.ev_bb - best.ev_bb)}`)
    // the best row still says so, with nothing in its "vs best" cell
    expect(cells(rowOf(/^Bet 33%/))[2]).toBeEmptyDOMElement()
  })
})
