import type { DecisionData } from '../../lib/decision'
import { sizeText, sortedOptions } from '../../lib/decision'
import { formatEvBb, formatPct, MINUS, nowrapUnits } from '../../lib/format'
import { optionLabel } from '../../lib/result'
import { Badge } from '../ui'
import styles from './OptionsTable.module.css'

export interface OptionsTableProps {
  decision: DecisionData
}

const DASH = '—'

/** best EV minus this option's EV: an allowed rearrangement of two API numbers. */
function versusBest(evBb: number, bestEvBb: number): string {
  const diff = bestEvBb - evBb
  const text = formatEvBb(Math.abs(diff))
  if (text === '0 bb') return text
  return `${diff > 0 ? MINUS : '+'}${text}`
}

export function OptionsTable({ decision }: OptionsTableProps) {
  const rows = sortedOptions(decision.options)
  const best = decision.options.find((o) => o.is_best)
  return (
    <table className={styles.table}>
      <caption className={styles.caption}>
        Every option, best EV first. EV is in big blinds against Villain&rsquo;s whole range.
      </caption>
      <thead>
        <tr>
          <th scope="col">Option</th>
          <th scope="col">Size</th>
          <th scope="col" className={styles.num}>
            EV
          </th>
          <th scope="col" className={styles.num}>
            vs best
          </th>
          <th scope="col" className={`${styles.num} ${styles.wrap}`}>
            Villain folds
          </th>
          <th scope="col" className={`${styles.num} ${styles.wrap}`}>
            Equity when called
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((o) => (
          <tr
            key={`${o.label}-${o.to}`}
            className={styles.row}
            data-best={o.is_best || undefined}
            data-chosen={o.is_chosen || undefined}
          >
            <th scope="row">
              <div className={styles.label}>
                <span>{o.is_chosen ? decision.chosenLabel : optionLabel(o.label)}</span>
                {o.is_best && <Badge tone="best">Best</Badge>}
                {o.is_chosen && <Badge tone="neutral">You</Badge>}
              </div>
            </th>
            <td className={styles.wrap}>{nowrapUnits(sizeText(o, decision.context))}</td>
            <td className={styles.num}>{formatEvBb(o.ev_bb)}</td>
            <td className={styles.num}>
              {best && !o.is_best ? versusBest(o.ev_bb, best.ev_bb) : ''}
            </td>
            <td className={styles.num}>{o.fold_freq === null ? DASH : formatPct(o.fold_freq)}</td>
            <td className={styles.num}>
              {o.equity_vs_continue === null ? DASH : formatPct(o.equity_vs_continue, 1)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
