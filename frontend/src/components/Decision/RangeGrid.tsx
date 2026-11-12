import { GRID_RANKS, cellLabel } from '../../lib/grid'
import { formatPct } from '../../lib/format'
import styles from './RangeGrid.module.css'

export type Grid = (number | null)[][]

export interface RangeGridProps {
  grid: Grid
  /** the grid's accessible name, e.g. the narrowing step's label */
  label: string
}

/** 13x13 hand-class grid: fill opacity = weight, hatched = every combo blocked by known cards. */
export function RangeGrid({ grid, label }: RangeGridProps) {
  return (
    <div className={styles.grid} role="grid" aria-label={label}>
      <div className={styles.row} role="row">
        <span className={styles.corner} role="presentation" />
        {GRID_RANKS.map((rank) => (
          <span key={rank} className={styles.head} role="columnheader">
            {rank}
          </span>
        ))}
      </div>
      {GRID_RANKS.map((rank, r) => (
        <div key={rank} className={styles.row} role="row">
          <span className={styles.head} role="rowheader">
            {rank}
          </span>
          {GRID_RANKS.map((_, c) => {
            const w = grid[r]?.[c] ?? null
            const name = cellLabel(r, c)
            return (
              <span
                key={name}
                className={styles.cell}
                role="gridcell"
                aria-label={w === null ? `${name}, blocked` : `${name}, ${formatPct(w)} weight`}
                data-blocked={w === null ? '' : undefined}
                data-strong={w !== null && w > 0.5 ? '' : undefined}
                style={w === null ? undefined : { ['--w' as string]: w }}
              >
                <span aria-hidden="true" className={styles.text}>
                  {name}
                </span>
              </span>
            )
          })}
        </div>
      ))}
    </div>
  )
}
