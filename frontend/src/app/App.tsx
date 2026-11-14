import { useEffect, useRef, useState } from 'react'
import type { FlowApi, Shown } from './usePuzzleFlow'
import { usePuzzleFlow } from './usePuzzleFlow'
import { AnswerPanel } from '../components/AnswerPanel/AnswerPanel'
import type { DecisionDetailsHandle } from '../components/Decision/DecisionDetails'
import { DecisionDetails } from '../components/Decision/DecisionDetails'
import { HandReveal } from '../components/HandReveal/HandReveal'
import { HistoryPanel } from '../components/HistoryPanel/HistoryPanel'
import { ExplanationPanel } from '../components/Explanation/ExplanationPanel'
import { ResultSummary } from '../components/ResultSummary/ResultSummary'
import { ShortcutsOverlay } from '../components/ShortcutsOverlay/ShortcutsOverlay'
import { Table } from '../components/Table/Table'
import { TableCentre } from '../components/TableCentre/TableCentre'
import { TopBar } from '../components/TopBar/TopBar'
import * as client from '../api/client'
import { ProgressPage } from '../components/Progress/ProgressPage'
import type { ProgressApi } from '../components/Progress/ProgressPage'
import { decisionFromAttempt } from '../lib/decision'
import { useExplanation } from './useExplanation'
import { usePage } from '../lib/page'
import type { Command } from '../lib/shortcuts'
import { useShortcuts } from '../lib/shortcuts'
import { answerEntry, heroFolded, VERDICT_LABELS, verdictLine } from '../lib/result'
import { seatsFromView } from '../lib/seats'
import styles from './App.module.css'

const SHORTCUTS_KEY = 'ppt.shortcuts'

// Deal timings (ms). On a new puzzle everything lands within 600 ms; input is never blocked.
const HOLE_DEAL_MS = [0, 120] // Hero's cards; Villain's are 60 ms after each
const HOLE_STAGGER_MS = 60
const BOARD_DEAL_BASE_MS = 80
const BOARD_DEAL_STAGGER_MS = 40
// On reveal the run-out comes after Villain's cards turn over.
const RUNOUT_BASE_MS = 380 // --duration-flip
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
  /** the stats API (the real client by default; a fake in tests) */
  progressApi?: ProgressApi
}

export function App({ api, progressApi = client }: AppProps = {}) {
  const [page, navigate] = usePage()
  // Landing on /progress doesn't generate a puzzle: the flow loads when Puzzles is first shown.
  const [puzzlesSeen, setPuzzlesSeen] = useState(page === 'puzzles')
  if (page === 'puzzles' && !puzzlesSeen) setPuzzlesSeen(true)
  const onPuzzles = page === 'puzzles'
  const flow = usePuzzleFlow(api, { enabled: puzzlesSeen })
  const { state, settings } = flow
  const [helpOpen, setHelpOpen] = useState(false)
  const [shortcutsOn, setShortcutsOnState] = useState(readShortcutsOn)
  // shortcuts belong to the Puzzles page; the play area stays mounted (hidden) on Progress
  const keysOn = shortcutsOn && !helpOpen && onPuzzles

  const slotRef = useRef<HTMLDivElement>(null)
  const nextRef = useRef<HTMLButtonElement>(null)
  const detailsRef = useRef<DecisionDetailsHandle>(null)

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
      case 'escape': {
        if (skipPending) {
          flow.cancelSkip()
          return true
        }
        // leave any focused control (the top bar's selects too), so single keys work again
        const active = document.activeElement
        if (
          active instanceof HTMLElement &&
          active !== document.body &&
          active !== slotRef.current
        ) {
          active.blur()
          return true
        }
        return false
      }
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

  // A page switch: back to the top, the tab's title follows, and Progress's heading takes focus
  // (the link that was clicked has just left the page's flow). Not on the first render.
  const titleRef = useRef<HTMLHeadingElement>(null)
  const switchedFrom = useRef(page) // also makes StrictMode's second effect run a no-op
  useEffect(() => {
    document.title =
      page === 'progress' ? 'Progress · Poker Puzzle Trainer' : 'Poker Puzzle Trainer'
    if (switchedFrom.current === page) return
    switchedFrom.current = page
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' })
    if (page === 'progress') titleRef.current?.focus({ preventScroll: true })
  }, [page])

  const onNewPuzzle = () => {
    if (state.kind === 'answering') flow.requestSkip()
    else flow.newPuzzle()
  }

  const explained = useExplanation(result, settings)
  const showPotOdds = settings?.show_pot_odds ?? true
  const showProfile = settings?.show_profile ?? true

  return (
    <div className={styles.app}>
      <TopBar
        page={page}
        onNavigate={navigate}
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
        {onPuzzles && state.kind === 'error' && (
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
        {onPuzzles && skipPending && (
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

      {page === 'progress' && (
        <main className={styles.progress}>
          <ProgressPage
            api={progressApi}
            profiles={settings?.profiles ?? null}
            titleRef={titleRef}
            goal={settings?.daily_goal ?? null}
            onGoal={(goal) => flow.setSetting({ daily_goal: goal })}
            onNavigate={navigate}
            onReplay={(id) => {
              // ignored while a load or a submit is in flight: then stay on Progress
              if (flow.openPuzzle(id)) navigate('puzzles')
            }}
            onResult={(attemptId) => {
              if (flow.openAttempt(attemptId)) navigate('puzzles')
            }}
          />
        </main>
      )}

      {/* hidden, not unmounted, on Progress: a half-entered answer survives the visit */}
      <main className={styles.main} aria-busy={pending || undefined} hidden={!onPuzzles}>
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
                    board={result && !heroFolded(result) ? result.reveal.runout : view.board}
                    potChips={view.pot}
                    potOdds={view.pot_odds}
                    showPotOdds={showPotOdds}
                    dealFrom={result && !heroFolded(result) ? view.board.length : 0}
                    dealBaseMs={result ? RUNOUT_BASE_MS : BOARD_DEAL_BASE_MS}
                    dealStaggerMs={result ? RUNOUT_STAGGER_MS : BOARD_DEAL_STAGGER_MS}
                  />
                }
              />
              <div ref={slotRef} className={styles.slot} tabIndex={-1} aria-label="Answer">
                {result ? (
                  <ResultSummary
                    ref={nextRef}
                    result={result}
                    onNext={flow.newPuzzle}
                    loading={state.kind === 'loading'}
                    shortcutsOn={shortcutsOn}
                    onDetails={() => detailsRef.current?.reveal()}
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
            {result && (
              <div className={styles.details} data-pending={pending || undefined}>
                <DecisionDetails
                  ref={detailsRef}
                  decision={decisionFromAttempt(view, result)}
                  whyTab={
                    <ExplanationPanel
                      explanation={explained?.explanation ?? result.explanation}
                      pendingModel={explained?.pendingModel}
                      requestFailed={explained?.requestFailed}
                      llmStatus={settings?.llm_status}
                      llmDetail={settings?.llm_detail}
                    />
                  }
                  handTab={<HandReveal view={view} result={result} />}
                />
              </div>
            )}
          </>
        )}
      </main>

      {/* always mounted, so screen readers announce the verdict when its text arrives */}
      <div className={styles.srOnly} role="status" aria-live="polite" data-testid="announcer">
        {state.kind === 'result'
          ? `${VERDICT_LABELS[state.result.grade.verdict]}. ${verdictLine(state.result)}`
          : ''}
      </div>

      <ShortcutsOverlay open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  )
}
