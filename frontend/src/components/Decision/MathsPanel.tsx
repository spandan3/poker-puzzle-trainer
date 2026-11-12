import { useId } from 'react'
import type { OptionResult } from '../../api/types'
import type { DecisionData } from '../../lib/decision'
import { formatEvBb } from '../../lib/format'
import type { MathsLine, OptionMaths } from '../../lib/maths'
import { optionMaths } from '../../lib/maths'
import styles from './MathsPanel.module.css'

export interface MathsPanelProps {
  decision: DecisionData
}

const DASH = '—'

function Lines({ title, lines }: { title: string; lines: MathsLine[] }) {
  if (lines.length === 0) return null
  return (
    <div className={styles.block}>
      <h4 className={styles.blockTitle}>{title}</h4>
      <div className={styles.formula}>
        {lines.map((line, i) => (
          <div key={i} className={styles.line}>
            <span>{line.text}</span>
            {line.result !== undefined && <span className={styles.result}>{line.result}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

function Branches({ maths }: { maths: OptionMaths }) {
  if (maths.branches.length === 0) return null
  return (
    <table className={styles.table}>
      <caption className={styles.caption}>
        Villain&rsquo;s replies. Value is what this option is worth in that case; e is your equity
        against that part of his range.
      </caption>
      <thead>
        <tr>
          <th scope="col">Villain&rsquo;s reply</th>
          <th scope="col" className={styles.num}>
            Share
          </th>
          <th scope="col" className={styles.num}>
            e
          </th>
          <th scope="col" className={styles.num}>
            Value
          </th>
          <th scope="col">Working</th>
        </tr>
      </thead>
      <tbody>
        {maths.branches.map((b) => (
          <tr key={b.label}>
            <th scope="row">{b.label}</th>
            <td className={styles.num}>{b.share}</td>
            <td className={styles.num}>{b.equity ?? DASH}</td>
            <td className={styles.num}>{b.value}</td>
            <td className={styles.working}>{b.formula ?? DASH}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Column({ option, decision }: { option: OptionResult; decision: DecisionData }) {
  const id = useId()
  const maths = optionMaths(option, decision)
  const role = [maths.isChosen && 'Your play', maths.isBest && 'Best play']
    .filter(Boolean)
    .join(' · ')
  return (
    <section className={styles.column} aria-labelledby={id}>
      <h3 id={id} className={styles.heading}>
        <span className={styles.role}>{role}</span>
        <span className={styles.label}>{maths.label}</span>
      </h3>
      <Lines title="Pot odds" lines={maths.potOdds} />
      <Lines title="Fold equity" lines={maths.foldEquity} />
      <Lines title="EV" lines={maths.ev} />
      <Branches maths={maths} />
      {maths.notes.length > 0 && (
        <ul className={styles.notes}>
          {maths.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** Your play and the best play, worked through step by step from the API's numbers. */
export function MathsPanel({ decision }: MathsPanelProps) {
  const chosen = decision.options.find((o) => o.is_chosen)
  const best = decision.options.find((o) => o.is_best)
  const shown = [chosen, best].filter(
    (o, i, all): o is OptionResult => o !== undefined && all.indexOf(o) === i,
  )
  return (
    <div className={styles.panel}>
      <div className={styles.columns} data-count={shown.length}>
        {shown.map((o) => (
          <Column key={`${o.label}-${o.to}`} option={o} decision={decision} />
        ))}
      </div>
      <p className={styles.loss}>
        EV lost = best − yours = <strong>{formatEvBb(decision.grade.ev_loss_bb)}</strong>
      </p>
    </div>
  )
}
