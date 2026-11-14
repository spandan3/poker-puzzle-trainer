import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { statsFixture } from '../../test/fixture'
import { LeakList } from './LeakList'

describe('LeakList', () => {
  it('shows each leak title and detail, and the cost only for share rules', () => {
    const leaks = statsFixture().leaks
    expect(leaks.map((l) => l.kind)).toEqual(['share', 'mean'])
    render(<LeakList leaks={leaks} />)
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('Folding too often')
    expect(items[0]).toHaveTextContent(leaks[0]!.detail)
    expect(items[0]).toHaveTextContent('136.2 bb lost')
    expect(items[1]).toHaveTextContent('Overestimating your equity')
    expect(items[1]).toHaveTextContent(leaks[1]!.detail)
    expect(items[1]).not.toHaveTextContent('lost')
  })

  it('rounds the cost half up, like the backend (0.15 is "0.2 bb", not "0.1")', () => {
    const leak = { ...statsFixture().leaks[0]!, ev_lost_bb: 0.15 }
    render(<LeakList leaks={[leak]} />)
    expect(screen.getByText('0.2 bb lost')).toBeVisible()
  })

  it('has a section heading with each leak title one level below', () => {
    render(<LeakList leaks={statsFixture().leaks} />)
    expect(screen.getByRole('heading', { level: 3, name: 'Leaks' })).toBeVisible()
    expect(screen.getByRole('heading', { level: 4, name: 'Folding too often' })).toBeVisible()
  })

  it('says so when there are none', () => {
    render(<LeakList leaks={[]} />)
    expect(screen.getByText('No leaks spotted in your last 200 puzzles.')).toBeVisible()
    expect(screen.queryByRole('list')).toBeNull()
  })
})
