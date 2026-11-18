import { forwardRef } from 'react'
import type { PlayHandView } from '../../api/types'
import { resultLine } from '../../lib/play'
import { Button } from '../ui'
import styles from './Play.module.css'

export interface HandOverPanelProps {
  hand: PlayHandView
  mustRebuy: boolean
  canTopUp: boolean
  /** a request is in flight: Next hand does nothing */
  busy: boolean
  /** `topUp` is the checkbox's value */
  onNext: (topUp: boolean) => void
  onAnalyse: (handId: number) => void
  shortcutsOn: boolean
  /** the checkbox is lifted so `N` can read it */
  topUp: boolean
  onTopUp: (on: boolean) => void
}

/** In place of the action panel when the hand is over: the result, Next hand, Analyse. */
export const HandOverPanel = forwardRef<HTMLButtonElement, HandOverPanelProps>(
  function HandOverPanel(
    { hand, mustRebuy, canTopUp, busy, onNext, onAnalyse, shortcutsOn, topUp, onTopUp },
    nextRef,
  ) {
    const outcome = hand.outcome
    const showdown = outcome?.showdown
    return (
      <section className={styles.over} aria-label="Hand over">
        {outcome && (
          <p className={styles.result} role="status">
            {resultLine(outcome)}
          </p>
        )}
        {showdown && (
          <p className={styles.hands}>
            You: {showdown.hero_hand} · Villain: {showdown.villain_hand}
          </p>
        )}
        <div className={styles.actions}>
          <Button
            ref={nextRef}
            variant="primary"
            busy={busy}
            kbd={shortcutsOn ? 'N' : undefined}
            // the page's own focus target: App leaves it alone after a navigation
            data-primary-focus=""
            onClick={() => onNext(topUp)}
            {...(shortcutsOn ? { 'data-shortcut': 'next', 'aria-keyshortcuts': 'N' } : {})}
          >
            {mustRebuy ? 'Rebuy and deal' : 'Next hand'}
          </Button>
          {hand.decision_count > 0 && (
            <Button variant="secondary" onClick={() => onAnalyse(hand.id)}>
              Analyse this hand
            </Button>
          )}
          {canTopUp && (
            <label className={styles.topUp}>
              <input type="checkbox" checked={topUp} onChange={(e) => onTopUp(e.target.checked)} />
              Top up to 100 bb
            </label>
          )}
        </div>
      </section>
    )
  },
)
