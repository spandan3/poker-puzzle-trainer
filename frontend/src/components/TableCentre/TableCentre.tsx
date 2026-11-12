import { cardName } from '../../lib/cards'
import { formatBb, formatPct } from '../../lib/format'
import { Card } from '../Card/Card'
import styles from './TableCentre.module.css'

export interface TableCentreProps {
  /** Dealt board cards (0 to 5). */
  board: string[]
  /** The pot in chips, including bets in front of the seats. */
  potChips: number
  potOdds: number | null
  showPotOdds: boolean
  /**
   * Board cards from this index slide in (staggered by `dealStaggerMs` after `dealBaseMs`):
   * 0 on a new puzzle, the dealt count when the run-out is revealed. No animation when omitted.
   */
  dealFrom?: number
  dealBaseMs?: number
  dealStaggerMs?: number
}

const SLOTS = 5

/** Board, pot and pot odds, sized to fit the centre budget of the table (22em × 10em). */
export function TableCentre({
  board,
  potChips,
  potOdds,
  showPotOdds,
  dealFrom,
  dealBaseMs = 0,
  dealStaggerMs = 60,
}: TableCentreProps) {
  const slots: (string | null)[] = [
    ...board,
    ...Array<null>(Math.max(0, SLOTS - board.length)).fill(null),
  ]
  const summary = board.length > 0 ? board.map(cardName).join(', ') : 'no cards yet'
  const pct = potOdds !== null && showPotOdds ? formatPct(potOdds) : null
  return (
    <div className={styles.centre} data-centre-budget="">
      <span className={styles.srOnly}>Board: {summary}</span>
      <div className={styles.board} aria-hidden="true">
        {slots.map((card, i) => (
          <Card
            // keyed by card, so a slot that gets a card re-mounts and slides in
            key={card ?? `slot-${i}`}
            card={card}
            size="md"
            dealDelayMs={
              card !== null && dealFrom !== undefined && i >= dealFrom
                ? dealBaseMs + (i - dealFrom) * dealStaggerMs
                : undefined
            }
          />
        ))}
      </div>
      <p key={potChips} className={styles.pot} data-fade="">
        Pot {formatBb(potChips)}
      </p>
      {pct !== null && <p className={styles.odds}>Pot odds: call needs {pct} equity</p>}
    </div>
  )
}
