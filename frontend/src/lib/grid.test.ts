import { describe, expect, it } from 'vitest'
import { cellLabel } from './grid'

// (row, col) = backend grid_position(label)
describe('cellLabel', () => {
  it.each([
    ['AA', 0, 0],
    ['AKs', 0, 1],
    ['AKo', 1, 0],
    ['72o', 12, 7],
    ['22', 12, 12],
  ])('%s sits at (%i, %i)', (label, row, col) => {
    expect(cellLabel(row, col)).toBe(label)
  })

  it('gives 169 distinct labels', () => {
    const all = new Set<string>()
    for (let r = 0; r < 13; r++) for (let c = 0; c < 13; c++) all.add(cellLabel(r, c))
    expect(all.size).toBe(169)
  })

  it('rejects cells off the grid', () => {
    expect(() => cellLabel(13, 0)).toThrow(RangeError)
  })
})
