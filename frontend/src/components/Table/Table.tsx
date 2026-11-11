import type { ReactNode } from 'react'
import type { SeatInfo } from '../../lib/seats'
import { Seat } from '../Seat/Seat'
import styles from './Table.module.css'

export interface TableProps {
  seats: SeatInfo[]
  /** Board, pot and pot odds: drawn in the middle of the felt. */
  centre: ReactNode
}

/** The oval table: a felt inside a rail, with seats placed by slot around it. */
export function Table({ seats, centre }: TableProps) {
  return (
    <section className={styles.table} aria-label="Poker table">
      <div className={styles.scale}>
        <div className={styles.rail}>
          <div className={styles.felt}>
            <div className={styles.centre}>{centre}</div>
          </div>
          {seats.map((seat) => (
            <Seat key={seat.slot} seat={seat} className={styles.seat} />
          ))}
        </div>
      </div>
    </section>
  )
}
