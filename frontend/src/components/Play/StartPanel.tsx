import { Fragment, useId, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { PlaySessionSummary, TableSize } from '../../api/types'
import { signedBbFromBb } from '../../lib/play'
import { Badge, Button, Panel } from '../ui'
import type { SessionHandsApi } from './SessionHands'
import { SessionHands } from './SessionHands'
import styles from './Play.module.css'

export const HELP_NOTE =
  'Pre-flop, the bot responds the same way to a 2.5x and a 3x open or 3-bet, and treats an all-in as a jam. There is no limping and no small 4-bet.'

export interface StartPanelProps {
  /** Start was clicked, with the mode chosen (2: heads-up, 5: 5-max). */
  onStart: (tableSize: TableSize) => void
  /** a request is in flight */
  busy: boolean
  /** past sessions, newest first (null: not loaded yet) */
  past: PlaySessionSummary[] | null
  /** a past session's hand was picked to analyse or review */
  onOpenHand: (handId: number) => void
  api?: SessionHandsApi
  /** changes when a hand list may have changed (an analysis was closed): open lists reload */
  refreshKey?: string | number
}

const MODE_KEY = 'play.tableSize'
const MODES: { size: TableSize; label: string }[] = [
  { size: 2, label: 'Heads-up' },
  { size: 5, label: '5-max' },
]

function readMode(): TableSize {
  try {
    return window.localStorage.getItem(MODE_KEY) === '5' ? 5 : 2
  } catch {
    return 2
  }
}

function writeMode(size: TableSize): void {
  try {
    window.localStorage.setItem(MODE_KEY, String(size))
  } catch {
    // storage blocked: the choice lasts for this page only
  }
}

function dateText(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Shown when there is no open session: start one, see the old ones, read what the bot does. */
export function StartPanel({ onStart, busy, past, onOpenHand, api, refreshKey }: StartPanelProps) {
  const [expanded, setExpanded] = useState<number | null>(null)
  const [mode, setMode] = useState<TableSize>(readMode)
  const modeLabelId = useId()
  const pick = (size: TableSize) => {
    setMode(size)
    writeMode(size)
  }
  const onModeKeys = (e: KeyboardEvent<HTMLDivElement>) => {
    const step =
      e.key === 'ArrowRight' || e.key === 'ArrowDown'
        ? 1
        : e.key === 'ArrowLeft' || e.key === 'ArrowUp'
          ? -1
          : 0
    if (step === 0) return
    e.preventDefault()
    const next =
      MODES[(MODES.findIndex((m) => m.size === mode) + step + MODES.length) % MODES.length]!
    pick(next.size)
    const buttons = e.currentTarget.querySelectorAll<HTMLButtonElement>('button')
    buttons[MODES.indexOf(next)]?.focus()
  }
  return (
    <section className={styles.start} aria-label="Start a session">
      <h2 className={styles.startTitle}>Play against a bot</h2>
      <p className={styles.startText}>
        {mode === 2
          ? 'A heads-up cash game, 100 bb deep, against one bot with a random profile. Play full hands, then analyse any hand afterwards.'
          : 'A 5-handed cash game, 100 bb deep, against four bots with random profiles. Side pots and all-ins are played in full. 5-max hands cannot be analysed yet.'}
      </p>
      <div className={styles.mode}>
        <span id={modeLabelId} className={styles.modeLegend}>
          Table
        </span>
        <div
          role="radiogroup"
          aria-labelledby={modeLabelId}
          className={styles.modeButtons}
          onKeyDown={onModeKeys}
        >
          {MODES.map((m) => (
            <button
              key={m.size}
              type="button"
              role="radio"
              aria-checked={m.size === mode}
              tabIndex={m.size === mode ? 0 : -1}
              className={styles.modeButton}
              onClick={() => pick(m.size)}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>
      <Button variant="primary" busy={busy} onClick={() => onStart(mode)}>
        Start session
      </Button>

      {past !== null && past.length > 0 && (
        <Panel title="Past sessions" flush className={styles.past}>
          <div className={styles.tableWrap}>
            <table className={styles.table} aria-label="Past sessions">
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Profile</th>
                  <th scope="col" className={styles.num}>
                    Hands
                  </th>
                  <th scope="col" className={styles.num}>
                    Net
                  </th>
                  <th scope="col">
                    <span className={styles.srOnly}>Hands list</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {past.map((s) => (
                  <Fragment key={s.id}>
                    <tr>
                      <th scope="row">
                        {dateText(s.created_at)}
                        {s.open && <span className={styles.pastOpen}> open</span>}
                      </th>
                      <td>
                        <Badge tone="profile">{s.profile_label}</Badge>
                      </td>
                      <td className={styles.num}>{s.hands_played}</td>
                      <td className={styles.num}>{signedBbFromBb(s.net_bb)}</td>
                      <td className={styles.num}>
                        {s.hands_played > 0 && (
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-expanded={expanded === s.id}
                            aria-label={`Hands of session ${s.id}`}
                            onClick={() => setExpanded(expanded === s.id ? null : s.id)}
                          >
                            Hands
                          </Button>
                        )}
                      </td>
                    </tr>
                    {expanded === s.id && (
                      <tr>
                        <td colSpan={5} className={styles.pastHandList}>
                          <SessionHands
                            sessionId={s.id}
                            api={api}
                            onOpen={onOpenHand}
                            refreshKey={refreshKey}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      <p className={styles.note}>{HELP_NOTE}</p>
    </section>
  )
}
