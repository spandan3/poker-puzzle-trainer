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
    expect(items[0]).toHaveTextContent('140.2 bb lost')
    expect(items[1]).toHaveTextContent('Overestimating your equity')
    expect(items[1]).toHaveTextContent(leaks[1]!.detail)
    expect(items[1]).not.toHaveTextContent('lost')
  })

  it('says so when there are none', () => {
    render(<LeakList leaks={[]} />)
    expect(screen.getByText('No leaks spotted in your last 200 puzzles.')).toBeVisible()
    expect(screen.queryByRole('list')).toBeNull()
  })
})
