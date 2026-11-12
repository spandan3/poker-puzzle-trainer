import { useEffect, useRef, useState } from 'react'
import type { FlowApi, Shown } from './usePuzzleFlow'
import { usePuzzleFlow } from './usePuzzleFlow'
import { AnswerPanel } from '../components/AnswerPanel/AnswerPanel'
import { HistoryPanel } from '../components/HistoryPanel/HistoryPanel'
import { ResultStrip } from '../components/ResultStrip/ResultStrip'
import { ShortcutsOverlay } from '../components/ShortcutsOverlay/ShortcutsOverlay'
import { Table } from '../components/Table/Table'
import { TableCentre } from '../components/TableCentre/TableCentre'
import { TopBar } from '../components/TopBar/TopBar'
import type { Command } from '../lib/shortcuts'
import { useShortcuts } from '../lib/shortcuts'
import { answerEntry } from '../lib/result'
import { seatsFromView } from '../lib/seats'
import styles from './App.module.css'

const SHORTCUTS_KEY = 'ppt.shortcuts'

// Deal timings (ms). On a new puzzle everything lands within 600 ms; input is never blocked.
const HOLE_DEAL_MS = [0, 120] // Hero's cards; Villain's are 60 ms after each
const HOLE_STAGGER_MS = 60
const BOARD_DEAL_BASE_MS = 80
const BOARD_DEAL_STAGGER_MS = 40
// On reveal the run-out comes after Villain's cards turn over.
const RUNOUT_BASE_MS = 200
const RUNOUT_STAGGER_MS = 120

function readShortcutsOn(): boolean {
  try {
    return window.localStorage.getItem(SHORTCUTS_KEY) !== 'off'
  } catch {
    return true
  }
}

function writeShortcutsOn(on: boolean): void {
  try {
    window.localStorage.setItem(SHORTCUTS_KEY, on ? 'on' : 'off')
  } catch {
    // storage blocked: the choice lasts for this page only
  }
}

export interface AppProps {
  /** the API (a fake in tests) */
  api?: FlowApi
}

export function App({ api }: AppProps = {}) {
  const flow = usePuzzleFlow(api)
  const { state, settings } = flow
  const [helpOpen, setHelpOpen] = useState(false)
  const [shortcutsOn, setShortcutsOnState] = useState(readShortcutsOn)
  const keysOn = shortcutsOn && !helpOpen

  const slotRef = useRef<HTMLDivElement>(null)
  const nextRef = useRef<HTMLButtonElement>(null)

  const setShortcutsOn = (on: boolean) => {
    setShortcutsOnState(on)
    writeShortcutsOn(on)
  }

  const skipPending = state.kind === 'answering' && state.skipPending

  const onCommand = (cmd: Command): boolean => {
    switch (cmd.id) {
      case 'next':
        flow.requestSkip()
        return true
      case 'help':
        setHelpOpen((open) => !open)
        return true
      case 'escape':
        if (!skipPending) return false
        flow.cancelSkip()
        return true
      default:
        return false
    }
  }
  useShortcuts(onCommand, keysOn)

  // What the page shows: the live state, or what was shown before a load or an error, so the
  // layout never collapses between puzzles.
  const shown: Shown | null =
    state.kind === 'answering' || state.kind === 'submitting'
      ? { view: state.view, result: null }
      : state.kind === 'result'
        ? { view: state.view, result: state.result }
        : state.previous
  const pending = state.kind === 'loading' || state.kind === 'error'
  const view = shown?.view ?? null
  const result = shown?.result ?? null

  // Keep keyboard focus on the page when the panel under it is swapped: the Next button when a
  // result arrives, else the panel slot (never a text box: that would pause the shortcuts).
  useEffect(() => {
    if (state.kind === 'result') {
      nextRef.current?.focus({ preventScroll: true })
      return
    }
    const active = document.activeElement
    if (active === null || active === document.body || !active.isConnected) {
      slotRef.current?.focus({ preventScroll: true })
    }
  }, [state.kind, view?.id])

  const onNewPuzzle = () => {
    if (state.kind === 'answering') flow.requestSkip()
    else flow.newPuzzle()
  }

  const showPotOdds = settings?.show_pot_odds ?? true
  const showProfile = settings?.show_profile ?? true

  return (
    <div className={styles.app}>
      <TopBar
        street={flow.street}
        onStreet={flow.setStreet}
        profile={settings?.profile ?? null}
        profiles={settings?.profiles ?? []}
        onProfile={(profile) => flow.setSetting({ profile })}
        showPotOdds={showPotOdds}
        onShowPotOdds={(on) => flow.setSetting({ show_pot_odds: on })}
        showProfile={showProfile}
        onShowProfile={(on) => flow.setSetting({ show_profile: on })}
        shortcutsOn={shortcutsOn}
        onShortcutsOn={setShortcutsOn}
        onHelp={() => setHelpOpen(true)}
        onNewPuzzle={onNewPuzzle}
      />

      <div className={styles.toasts}>
        {state.kind === 'error' && (
          <div className={styles.banner} role="alert" data-tone="danger">
            <span>{state.message}</span>
            <button type="button" className={styles.bannerButton} onClick={state.retry}>
              Retry
            </button>
          </div>
        )}
        {flow.notice !== null && (
          <div className={styles.banner} role="alert" data-tone="warning">
            <span>{flow.notice}</span>
            <button type="button" className={styles.bannerButton} onClick={flow.dismissNotice}>
              Dismiss
            </button>
          </div>
        )}
        {skipPending && (
          <div className={styles.banner} role="status" data-tone="info">
            <span>
              Skip this puzzle? Press <kbd className={styles.kbd}>N</kbd> again
            </span>
            <button type="button" className={styles.bannerButton} onClick={flow.requestSkip}>
              Skip
            </button>
            <button type="button" className={styles.bannerButton} onClick={flow.cancelSkip}>
              Cancel
            </button>
          </div>
        )}
      </div>

      <main className={styles.main} aria-busy={pending || undefined}>
        {view === null ? (
          <div className={styles.empty} role="status">
            {state.kind === 'error' ? 'No puzzle loaded' : 'Dealing…'}
          </div>
        ) : (
          <>
            <div className={styles.play} data-pending={pending || undefined}>
              <Table
                // a new puzzle re-mounts the table, so the cards deal in again
                key={view.id}
                seats={seatsFromView(view, {
                  showProfile,
                  villainCards: result?.reveal.villain_cards,
                }).map((seat) => ({
                  ...seat,
                  dealDelaysMs: result
                    ? undefined
                    : HOLE_DEAL_MS.map((ms) => ms + (seat.isHero ? 0 : HOLE_STAGGER_MS)),
                  flip: result !== null && !seat.isHero,
                }))}
                centre={
                  <TableCentre
                    board={result ? result.reveal.runout : view.board}
                    potChips={view.pot}
                    potOdds={view.pot_odds}
                    showPotOdds={showPotOdds}
                    dealFrom={result ? view.board.length : 0}
                    dealBaseMs={result ? RUNOUT_BASE_MS : BOARD_DEAL_BASE_MS}
                    dealStaggerMs={result ? RUNOUT_STAGGER_MS : BOARD_DEAL_STAGGER_MS}
                  />
                }
              />
              <div ref={slotRef} className={styles.slot} tabIndex={-1} aria-label="Answer">
                {result ? (
                  <ResultStrip
                    ref={nextRef}
                    result={result}
                    onNext={flow.newPuzzle}
                    loading={pending}
                    shortcutsOn={shortcutsOn}
                  />
                ) : (
                  <AnswerPanel
                    view={view}
                    onSubmit={flow.submit}
                    busy={state.kind !== 'answering'}
                    error={state.kind === 'answering' ? state.error : null}
                    customDisabledReason={
                      state.kind === 'answering' || state.kind === 'submitting'
                        ? state.customDisabledReason
                        : null
                    }
                    shortcutsOn={keysOn}
                  />
                )}
              </div>
            </div>
            <HistoryPanel
              view={view}
              answer={result ? answerEntry(view, result) : undefined}
              className={styles.side}
            />
          </>
        )}
      </main>

      <ShortcutsOverlay open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  )
}
