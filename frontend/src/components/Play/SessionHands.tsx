import { useEffect, useState } from 'react'
import * as client from '../../api/client'
import type { PlayHandSummary } from '../../api/types'
import { formatEvBb } from '../../lib/format'
import { signedBbFromBb } from '../../lib/play'
import { Button } from '../ui'
import styles from './SessionHands.module.css'

export type SessionHandsApi = Pick<typeof client, 'listPlayHands'>

export interface SessionHandsProps {
  sessionId: number
  api?: SessionHandsApi
  /** "Analyse" or "Review" was clicked */
  onOpen: (handId: number) => void
  /** changes when the list may have changed (a hand ended, an analysis was finished) */
  refreshKey?: string | number
  /**
   * A hand the screen still shows as running (the bot's reveal of its end is not over): its row
   * reads "In progress", with no result, whatever the API says, so the list never spoils it.
   */
  inProgressId?: number
}

type Loaded =
  | { sessionId: number; refreshKey: string | number | undefined; hands: PlayHandSummary[] }
  | { sessionId: number; refreshKey: string | number | undefined; failed: true }

/** A session's hands: number, position, result and EV lost when analysed, with Analyse / Review. */
export function SessionHands({
  sessionId,
  api = client,
  onOpen,
  refreshKey,
  inProgressId,
}: SessionHandsProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let live = true
    api.listPlayHands(sessionId).then(
      (hands) => live && setLoaded({ sessionId, refreshKey, hands }),
      () => live && setLoaded({ sessionId, refreshKey, failed: true }),
    )
    return () => {
      live = false
    }
  }, [api, sessionId, refreshKey, attempt])

  if (loaded === null || loaded.sessionId !== sessionId) {
    return <p className={styles.muted}>Loading hands…</p>
  }
  if ('failed' in loaded) {
    return (
      <div className={styles.muted} role="alert">
        <span>Couldn’t load the hands.</span>{' '}
        <Button
          size="sm"
          onClick={() => {
            setLoaded(null)
            setAttempt((n) => n + 1)
          }}
        >
          Retry
        </Button>
      </div>
    )
  }
  if (loaded.hands.length === 0) return <p className={styles.muted}>No hands yet.</p>
  return (
    <div className={styles.wrap}>
      <table className={styles.table} aria-label="Hands">
        <thead>
          <tr>
            <th scope="col">Hand</th>
            <th scope="col">Position</th>
            <th scope="col" className={styles.num}>
              Result
            </th>
            <th scope="col" className={styles.num}>
              EV lost
            </th>
            <th scope="col">
              <span className={styles.srOnly}>Analysis</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {loaded.hands.map((h) => {
            const running = h.ended_by === null || h.result_bb === null || h.id === inProgressId
            const verb = h.analysed ? 'Review' : 'Analyse'
            return (
              <tr key={h.id}>
                <th scope="row">Hand {h.hand_no}</th>
                <td>{h.hero_position}</td>
                <td className={styles.num}>
                  {running ? 'In progress' : signedBbFromBb(h.result_bb!)}
                </td>
                <td className={styles.num}>
                  {!running && h.analysed && h.ev_loss_bb !== null ? formatEvBb(h.ev_loss_bb) : ''}
                </td>
                <td className={styles.action}>
                  {h.decision_count > 0 && !running && (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`${verb} hand ${h.hand_no}`}
                      onClick={() => onOpen(h.id)}
                    >
                      {verb}
                    </Button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
