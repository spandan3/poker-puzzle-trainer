import type { AttemptResult } from '../../api/types'
import { formatPct } from '../../lib/format'
import styles from './CategoryTable.module.css'

export interface CategoryTableProps {
  categories: NonNullable<AttemptResult['categories']>
  /** Hero's overall standing against the whole range; `ahead` is null on the river */
  hero: { ahead: number | null; equity: number }
}

const DASH = '—'

/** Villain's range split into hand categories, with how Hero's hand does against each. */
export function CategoryTable({ categories, hero }: CategoryTableProps) {
  return (
    <table className={styles.table}>
      <caption className={styles.caption}>Your hand against each part of the range</caption>
      <thead>
        <tr>
          <th scope="col">Category</th>
          <th scope="col" className={styles.num}>
            Share of range
          </th>
          <th scope="col" className={styles.num}>
            You&apos;re ahead
          </th>
          <th scope="col" className={styles.num}>
            Your equity
          </th>
          <th scope="col">Win / Tie / Lose</th>
        </tr>
      </thead>
      <tbody>
        {categories.map((c) => (
          <tr key={c.category}>
            <th scope="row">{c.name}</th>
            <td className={styles.num}>{formatPct(c.share, 1)}</td>
            <td className={styles.num}>{formatPct(c.ahead)}</td>
            <td className={styles.num}>{formatPct(c.equity)}</td>
            <td>
              <span className={styles.bar} aria-hidden="true">
                <span data-kind="win" style={{ flexGrow: c.win }} />
                <span data-kind="tie" style={{ flexGrow: c.tie }} />
                <span data-kind="lose" style={{ flexGrow: c.lose }} />
              </span>
              <span className={styles.wtl}>
                {formatPct(c.win)} / {formatPct(c.tie)} / {formatPct(c.lose)}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row">Whole range</th>
          <td className={styles.num}>100%</td>
          <td className={styles.num}>{hero.ahead === null ? DASH : formatPct(hero.ahead)}</td>
          <td className={styles.num}>{formatPct(hero.equity)}</td>
          <td />
        </tr>
      </tfoot>
    </table>
  )
}
