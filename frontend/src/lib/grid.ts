/** Range-grid geometry. Mirrors backend engine/combos.py `_label`: grid index 0 = ace, 12 = deuce. */

export const GRID_RANKS = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2'] as const

/** Label of the cell at (row, col): pairs on the diagonal, suited above it, offsuit below it. */
export function cellLabel(row: number, col: number): string {
  const r = GRID_RANKS[row]
  const c = GRID_RANKS[col]
  if (r === undefined || c === undefined) throw new RangeError(`no grid cell (${row}, ${col})`)
  if (row === col) return r + c
  return row < col ? `${r}${c}s` : `${c}${r}o`
}
