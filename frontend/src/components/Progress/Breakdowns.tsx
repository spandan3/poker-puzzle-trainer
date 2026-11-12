import type { KeyboardEvent } from 'react'
import { useId, useRef, useState } from 'react'
import type { BreakdownRow, StatsView } from '../../api/types'
import { formatEvBb } from '../../lib/format'
import { pct, pts } from '../../lib/stats'
import styles from './Progress.module.css'

type TabId = 'street' | 'action' | 'profile'

const TABS: { id: TabId; label: string }[] = [
  { id: 'street', label: 'Street' },
  { id: 'action', label: 'Action' },
  { id: 'profile', label: 'Villain' },
]

export interface BreakdownsProps {
  breakdowns: StatsView['breakdowns']
}

function BreakdownTable({ rows, first }: { rows: BreakdownRow[]; first: string }) {
  if (rows.length === 0) return <p className={styles.hint}>No puzzles yet.</p>
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">{first}</th>
            <th scope="col" className={styles.num}>
              Puzzles
            </th>
            <th scope="col" className={styles.num}>
              Accuracy
            </th>
            <th scope="col" className={styles.num}>
              EV lost
            </th>
            <th scope="col" className={styles.num}>
              Equity error
            </th>
            <th scope="col" className={styles.num}>
              Best
            </th>
            <th scope="col" className={styles.num}>
              Fine
            </th>
            <th scope="col" className={styles.num}>
              Mistake
            </th>
            <th scope="col" className={styles.num}>
              Blunder
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <th scope="row">{r.label}</th>
              <td className={styles.num}>{r.count}</td>
              <td className={styles.num}>{pct(r.accuracy)}</td>
              <td className={styles.num}>{formatEvBb(r.ev_lost_bb_avg)}</td>
              <td className={styles.num}>{pts(r.equity_error_avg)}</td>
              <td className={styles.num}>{r.verdicts.best}</td>
              <td className={styles.num}>{r.verdicts.fine}</td>
              <td className={styles.num}>{r.verdicts.mistake}</td>
              <td className={styles.num}>{r.verdicts.blunder}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Accuracy by street, by action and by Villain profile, as WAI-ARIA tabs (rows in the API's order). */
export function Breakdowns({ breakdowns }: BreakdownsProps) {
  const baseId = useId()
  const [selected, setSelected] = useState<TabId>('street')
  const tabRefs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({})

  const select = (tab: TabId, focus = false) => {
    setSelected(tab)
    if (focus) tabRefs.current[tab]?.focus()
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const at = TABS.findIndex((t) => t.id === selected)
    let next: number
    if (e.key === 'ArrowRight') next = (at + 1) % TABS.length
    else if (e.key === 'ArrowLeft') next = (at - 1 + TABS.length) % TABS.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = TABS.length - 1
    else return
    e.preventDefault()
    select(TABS[next]!.id, true)
  }

  return (
    <section aria-labelledby={`${baseId}-title`} className={styles.section}>
      <h2 id={`${baseId}-title`} className={styles.h2}>
        Breakdown
      </h2>
      <div className={styles.card}>
        <div role="tablist" aria-label="Breakdown by" className={styles.tabs} onKeyDown={onKeyDown}>
          {TABS.map((tab) => (
            <button
              key={tab.id}
              ref={(el) => {
                tabRefs.current[tab.id] = el
              }}
              type="button"
              role="tab"
              id={`${baseId}-tab-${tab.id}`}
              aria-selected={tab.id === selected}
              aria-controls={`${baseId}-panel-${tab.id}`}
              tabIndex={tab.id === selected ? 0 : -1}
              className={styles.tab}
              onClick={() => select(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {TABS.map((tab) => (
          <div
            key={tab.id}
            role="tabpanel"
            id={`${baseId}-panel-${tab.id}`}
            aria-labelledby={`${baseId}-tab-${tab.id}`}
            hidden={tab.id !== selected}
            tabIndex={tab.id === selected ? 0 : undefined}
          >
            {tab.id === selected && <BreakdownTable rows={breakdowns[tab.id]} first={tab.label} />}
          </div>
        ))}
      </div>
    </section>
  )
}
