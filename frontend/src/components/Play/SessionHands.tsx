import { useEffect, useState } from 'react'
import * as client from '../../api/client'
import type { PlayHandSummary } from '../../api/types'
import { formatEvBb } from '../../lib/format'
import { signedBb } from '../../lib/play'
import styles from './SessionHands.module.css'

export type SessionHandsApi = Pick<typeof client, 'listPlayHands'>

export interface SessionHandsProps {
  sessionId: number
  api?: SessionHandsApi
  /** "Analyse" or "Review" was clicked */
  onOpen: (handId: number) => void
  /** changes when the list may have changed (a hand ended, an analysis was finished) */
  refreshKey?: string | number
}

type Loaded =
  | { sessionId: number; refreshKey: string | number | undefined; hands: PlayHandSummary[] }
  | { sessionId: number; refreshKey: string | number | undefined; failed: true }

/** A session's hands: number, position, result and EV lost when analysed, with Analyse / Review. */
export function SessionHands({ sessionId, api = client, onOpen, refreshKey }: SessionHandsProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)

  useEffect(() => {
    let live = true
    api.listPlayHands(sessionId).then(
      (hands) => live && setLoaded({ sessionId, refreshKey, hands }),
      () => live && setLoaded({ sessionId, refreshKey, failed: true }),
    )
    return () => {
      live = false
    }
  }, [api, sessionId, refreshKey])

  if (loaded === null || loaded.sessionId !== sessionId) {
    return <p className={styles.muted}>Loading hands…</p>
  }
  if ('failed' in loaded) return <p className={styles.muted}>Couldn’t load the hands.</p>
  if (loaded.hands.length === 0) return <p className={styles.muted}>No hands yet.</p>
  return (
    <ul className={styles.list} aria-label="Hands">
      {loaded.hands.map((h) => {
        const running = h.ended_by === null || h.result_bb === null
        const verb = h.analysed ? 'Review' : 'Analyse'
        return (
          <li key={h.id} className={styles.row}>
            <span className={styles.no}>Hand {h.hand_no}</span>
            <span className={styles.position}>{h.hero_position}</span>
            <span className={styles.result}>
              {running ? 'In progress' : signedBb(Math.round(h.result_bb! * 2))}
            </span>
            <span className={styles.loss}>
              {h.analysed && h.ev_loss_bb !== null ? `EV lost ${formatEvBb(h.ev_loss_bb)}` : ''}
            </span>
            {h.decision_count > 0 && !running ? (
              <button
                type="button"
                className={styles.open}
                aria-label={`${verb} hand ${h.hand_no}`}
                onClick={() => onOpen(h.id)}
              >
                {verb}
              </button>
            ) : (
              <span />
            )}
          </li>
        )
      })}
    </ul>
  )
}
