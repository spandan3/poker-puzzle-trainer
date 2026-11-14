import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type * as client from '../../api/client'
import { ApiError } from '../../api/client'
import type { AttemptSummary, HistoryPage, StreetName } from '../../api/types'
import { bbLabel, formatEvBb } from '../../lib/format'
import { STREET_LABELS, STREET_ORDER } from '../../lib/history'
import { optionLabel, VERDICT_LABELS } from '../../lib/result'
import { pts, shortDate } from '../../lib/stats'
import styles from './Progress.module.css'

/** Rows per page. */
export const HISTORY_PAGE_SIZE = 25

export type HistoryApi = Pick<typeof client, 'getHistory'>

export interface HistoryTableProps {
  api: HistoryApi
  /** Villain profiles for the filter and the Villain column (key = stored name) */
  profiles: { key: string; label: string }[]
  /** "Replay": answer this puzzle again (a practice attempt) */
  onReplay: (puzzleId: number) => void
  /** "Result": reopen this attempt's stored result */
  onResult: (attemptId: number) => void
}

type Verdict = AttemptSummary['verdict']
type ActionKind = AttemptSummary['action_kind']

interface Filters {
  street: StreetName | ''
  verdict: Verdict | ''
  action: ActionKind | ''
  profile: string
  firstOnly: boolean
}

const NO_FILTERS: Filters = { street: '', verdict: '', action: '', profile: '', firstOnly: false }

const VERDICTS: Verdict[] = ['best', 'fine', 'mistake', 'blunder']
const ACTIONS: ActionKind[] = ['fold', 'check', 'call', 'bet', 'raise']

/** A page and the offset it was fetched with (the range text must follow the rows on show). */
interface Shown {
  page: HistoryPage
  offset: number
}

type Load =
  | { kind: 'loading'; previous: Shown | null }
  | { kind: 'error'; message: string; previous: Shown | null }
  | { kind: 'ready'; shown: Shown }

/** The date an attempt was made, in the viewer's time zone: "Nov 12". */
function localDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  const pad = (n: number) => String(n).padStart(2, '0')
  return shortDate(`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`)
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 0) {
    return "Can't reach the server. Check it is running, then retry."
  }
  return "Couldn't load your history."
}

/** Your attempts, newest first, with filters, paging and a Replay and a Result button per row. */
export function HistoryTable({ api, profiles, onReplay, onResult }: HistoryTableProps) {
  const ids = useId()
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [load, setLoad] = useState<Load>({ kind: 'loading', previous: null })

  // Requests are sequenced: only the newest one may write. A request is sent once per distinct
  // query (StrictMode's second effect run finds the same key and sends nothing).
  const seq = useRef(0)
  const lastKey = useRef<string | null>(null)
  useEffect(() => {
    const key = JSON.stringify([filters, offset, reload])
    if (lastKey.current === key) return
    lastKey.current = key
    const mine = ++seq.current
    setLoad((now) => ({
      kind: 'loading',
      previous: now.kind === 'ready' ? now.shown : now.previous,
    }))
    api
      .getHistory({
        limit: HISTORY_PAGE_SIZE,
        offset,
        first_only: filters.firstOnly,
        street: filters.street || null,
        verdict: filters.verdict || null,
        action_kind: filters.action || null,
        profile: filters.profile || null,
      })
      .then(
        (page) => {
          if (mine === seq.current) setLoad({ kind: 'ready', shown: { page, offset } })
        },
        (error: unknown) => {
          if (mine !== seq.current) return
          setLoad((now) => ({
            kind: 'error',
            message: errorMessage(error),
            previous: now.kind === 'ready' ? now.shown : now.previous,
          }))
        },
      )
  }, [api, filters, offset, reload])

  const change = useCallback((patch: Partial<Filters>) => {
    setFilters((now) => ({ ...now, ...patch }))
    setOffset(0)
  }, [])

  const shown = load.kind === 'ready' ? load.shown : load.previous
  const total = shown?.page.total ?? 0
  const items = shown?.page.items ?? []
  const busy = load.kind === 'loading'
  // the range follows the rows on show, not the page being fetched
  const shownOffset = shown?.offset ?? 0
  const from = total === 0 ? 0 : shownOffset + 1
  const to = Math.min(shownOffset + HISTORY_PAGE_SIZE, total)
  const atStart = offset === 0
  const atEnd = offset + HISTORY_PAGE_SIZE >= total

  // The pager buttons stay enabled while a page loads (a click then does nothing) and are
  // disabled only at the ends. A button that has just become disabled must not hold focus: it
  // goes to the other one.
  const prevRef = useRef<HTMLButtonElement>(null)
  const nextRef = useRef<HTMLButtonElement>(null)
  const pressed = useRef<'prev' | 'next' | null>(null)
  useEffect(() => {
    const was = pressed.current
    if (was === null) return
    const [mine, other] =
      was === 'prev' ? [prevRef.current, nextRef.current] : [nextRef.current, prevRef.current]
    if (mine?.disabled === true) {
      if (other?.disabled === false) other.focus()
      pressed.current = null
    } else if (!busy) {
      pressed.current = null
    }
  })
  const page = (delta: number) => {
    if (busy) return
    pressed.current = delta < 0 ? 'prev' : 'next'
    setOffset(Math.max(0, offset + delta))
  }
  const labelOf = (key: string) => profiles.find((p) => p.key === key)?.label ?? key
  // a profile with no first attempt isn't in the stats' list; keep a chosen one selectable
  const profileOptions =
    filters.profile !== '' && !profiles.some((p) => p.key === filters.profile)
      ? [...profiles, { key: filters.profile, label: filters.profile }]
      : profiles

  return (
    <section className={styles.section} aria-labelledby={`${ids}-title`} data-testid="history">
      <h3 className={styles.sectionTitle} id={`${ids}-title`}>
        History
      </h3>

      <div className={styles.filters} role="group" aria-label="History filters">
        <label className={styles.filter}>
          <span>Street</span>
          <select
            className={styles.select}
            value={filters.street}
            onChange={(e) => change({ street: e.target.value as StreetName | '' })}
          >
            <option value="">All</option>
            {STREET_ORDER.map((s) => (
              <option key={s} value={s}>
                {STREET_LABELS[s]}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filter}>
          <span>Verdict</span>
          <select
            className={styles.select}
            value={filters.verdict}
            onChange={(e) => change({ verdict: e.target.value as Verdict | '' })}
          >
            <option value="">All</option>
            {VERDICTS.map((v) => (
              <option key={v} value={v}>
                {VERDICT_LABELS[v]}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filter}>
          <span>Action</span>
          <select
            className={styles.select}
            value={filters.action}
            onChange={(e) => change({ action: e.target.value as ActionKind | '' })}
          >
            <option value="">All</option>
            {ACTIONS.map((a) => (
              <option key={a} value={a}>
                {optionLabel(a)}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filter}>
          <span>Villain</span>
          <select
            className={styles.select}
            value={filters.profile}
            onChange={(e) => change({ profile: e.target.value })}
          >
            <option value="">All</option>
            {profileOptions.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.checkFilter}>
          <input
            type="checkbox"
            checked={filters.firstOnly}
            onChange={(e) => change({ firstOnly: e.target.checked })}
          />
          <span>First attempts only</span>
        </label>
      </div>

      {load.kind === 'error' && (
        <div className={styles.status} role="alert">
          <span>{load.message}</span>{' '}
          <button
            type="button"
            className={styles.button}
            onClick={() => {
              setReload((n) => n + 1)
            }}
          >
            Retry
          </button>
        </div>
      )}
      {load.kind === 'loading' && load.previous === null && (
        <p className={styles.status} role="status">
          Loading your history…
        </p>
      )}

      {shown !== null && (
        <>
          {items.length === 0 ? (
            <p className={styles.hint}>No attempts match these filters.</p>
          ) : (
            <div
              className={styles.tableWrap}
              aria-busy={busy || undefined}
              data-busy={busy || undefined}
            >
              <table className={styles.table}>
                <caption className={styles.srOnly}>Your attempts, newest first</caption>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Street</th>
                    <th scope="col">Villain</th>
                    <th scope="col">Your play</th>
                    <th scope="col">Best</th>
                    <th scope="col">Verdict</th>
                    <th scope="col" className={styles.num}>
                      EV lost
                    </th>
                    <th scope="col" className={styles.num}>
                      Equity error
                    </th>
                    <th scope="col">
                      <span className={styles.srOnly}>Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => {
                    // unique enough to tell rows apart: date, street, verdict, and "practice" for a retry
                    const when = [
                      localDate(row.created_at),
                      STREET_LABELS[row.street].toLowerCase(),
                      VERDICT_LABELS[row.verdict].toLowerCase(),
                      ...(row.is_first ? [] : ['practice']),
                    ].join(', ')
                    return (
                      <tr key={row.attempt_id}>
                        <td>
                          {localDate(row.created_at)}
                          {!row.is_first && (
                            <span
                              className={styles.badge}
                              title="A repeat attempt: not in your stats"
                            >
                              Practice
                            </span>
                          )}
                        </td>
                        <td>{STREET_LABELS[row.street]}</td>
                        <td>{labelOf(row.profile)}</td>
                        <td>{optionLabel(bbLabel(row.chosen_label))}</td>
                        <td>{optionLabel(bbLabel(row.best_label))}</td>
                        <td>
                          <span className={styles.verdict} data-verdict={row.verdict}>
                            {VERDICT_LABELS[row.verdict]}
                          </span>
                        </td>
                        <td className={styles.num}>{formatEvBb(row.ev_loss_bb)}</td>
                        <td className={styles.num}>{pts(row.equity_error)}</td>
                        <td className={styles.rowActions}>
                          <button
                            type="button"
                            className={styles.button}
                            aria-label={`Replay puzzle from ${when}`}
                            onClick={() => onReplay(row.puzzle_id)}
                          >
                            Replay
                          </button>
                          <button
                            type="button"
                            className={styles.button}
                            aria-label={`Result of the attempt from ${when}`}
                            onClick={() => onResult(row.attempt_id)}
                          >
                            Result
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          <nav className={styles.pager} aria-label="History pages">
            <button
              type="button"
              className={styles.button}
              ref={prevRef}
              disabled={atStart}
              onClick={() => page(-HISTORY_PAGE_SIZE)}
            >
              Previous
            </button>
            <span className={styles.hint} aria-live="polite" data-testid="history-range">
              {total === 0 ? '0 of 0' : `${from}–${to} of ${total}`}
            </span>
            <button
              type="button"
              className={styles.button}
              ref={nextRef}
              disabled={atEnd}
              onClick={() => page(HISTORY_PAGE_SIZE)}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </section>
  )
}
