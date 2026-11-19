import { useEffect, useRef, useState } from 'react'
import type { FlowApi, Shown } from './usePuzzleFlow'
import { usePuzzleFlow } from './usePuzzleFlow'
import type { PlayApi } from './usePlayFlow'
import { usePlayFlow } from './usePlayFlow'
import { AnswerPanel } from '../components/AnswerPanel/AnswerPanel'
import type { DecisionDetailsHandle } from '../components/Decision/DecisionDetails'
import { DecisionDetails } from '../components/Decision/DecisionDetails'
import { HandReveal } from '../components/HandReveal/HandReveal'
import { PlayPage } from '../components/Play/PlayPage'
import { HistoryPanel } from '../components/HistoryPanel/HistoryPanel'
import { ExplanationPanel } from '../components/Explanation/ExplanationPanel'
import { ResultSummary } from '../components/ResultSummary/ResultSummary'
import { ShortcutsOverlay } from '../components/ShortcutsOverlay/ShortcutsOverlay'
import { Table } from '../components/Table/Table'
import { TableCentre } from '../components/TableCentre/TableCentre'
import { Button, ConfirmDialog } from '../components/ui'
import { TopBar } from '../components/TopBar/TopBar'
import * as client from '../api/client'
import { SettingsPage } from '../components/Settings/SettingsPage'
import { ProgressPage } from '../components/Progress/ProgressPage'
import type { ProgressApi } from '../components/Progress/ProgressPage'
import { decisionFromAttempt } from '../lib/decision'
import {
  BOARD_DEAL_BASE_MS,
  BOARD_DEAL_STAGGER_MS,
  HOLE_DEAL_MS,
  HOLE_STAGGER_MS,
  RUNOUT_BASE_MS,
  RUNOUT_STAGGER_MS,
} from '../lib/dealTiming'
import { useExplanation } from './useExplanation'
import type { Page } from '../lib/page'
import { usePage } from '../lib/page'
import type { Command } from '../lib/shortcuts'
import { useShortcuts } from '../lib/shortcuts'
import { answerEntry, heroFolded, VERDICT_LABELS, verdictLine } from '../lib/result'
import { shownTally, tallyText } from '../lib/play'
import { seatsFromView } from '../lib/seats'
import styles from './App.module.css'
import layout from '../styles/tableLayout.module.css'

const SHORTCUTS_KEY = 'ppt.shortcuts'

const TITLES: Record<Page, string> = {
  puzzles: 'Poker Puzzle Trainer',
  play: 'Play · Poker Puzzle Trainer',
  progress: 'Progress · Poker Puzzle Trainer',
  settings: 'Settings · Poker Puzzle Trainer',
}

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
  /** the play API (the real client by default; a fake in tests) */
  playApi?: PlayApi
}

export function App({ api, progressApi = client, playApi }: AppProps = {}) {
  const [page, navigate] = usePage()
  // Landing on /progress doesn't generate a puzzle: the flow loads when Puzzles is first shown.
  const [puzzlesSeen, setPuzzlesSeen] = useState(page === 'puzzles')
  if (page === 'puzzles' && !puzzlesSeen) setPuzzlesSeen(true)
  const onPuzzles = page === 'puzzles'
  const onPlay = page === 'play'
  // Likewise, the play session loads when Play is first shown.
  const [playSeen, setPlaySeen] = useState(page === 'play')
  if (page === 'play' && !playSeen) setPlaySeen(true)
  const flow = usePuzzleFlow(api, { enabled: puzzlesSeen })
  const play = usePlayFlow(playApi, { enabled: playSeen })
  const { state, settings } = flow
  const [helpOpen, setHelpOpen] = useState(false)
  const [shortcutsOn, setShortcutsOnState] = useState(readShortcutsOn)
  // Shortcuts belong to the page on show; the Puzzles and Play pages stay mounted (hidden) on the
  // others. Each page binds its own keys: `N` is the skip on Puzzles and the next hand on Play.
  const keysOn = shortcutsOn && !helpOpen && onPuzzles
  const playKeysOn = shortcutsOn && !helpOpen && onPlay

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
        if (!onPuzzles) return false
        flow.requestSkip()
        return true
      case 'help':
        setHelpOpen((open) => !open)
        return true
      case 'escape': {
        if (skipPending && onPuzzles) {
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
  useShortcuts(onCommand, keysOn || playKeysOn)

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
  const runOut = result !== null && !heroFolded(result)

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

  // A page switch: back to the top and the tab's title follows. After a click on a nav link (a
  // user navigation: not the first render, not Back/Forward, not Replay) the page's heading takes
  // focus, because the link that was clicked has just left the page's flow. Unless the page has a
  // primary target of its own on show: Next puzzle (a result) or Next hand (a hand is over).
  const titleRef = useRef<HTMLHeadingElement>(null)
  const puzzlesHeadingRef = useRef<HTMLHeadingElement>(null)
  const playHeadingRef = useRef<HTMLHeadingElement>(null)
  const focusAfterNav = useRef(false)
  const goTo = (next: Page) => {
    // a click on the page already on show moves nothing, so it must not arm the next switch
    focusAfterNav.current = next !== page
    navigate(next)
  }
  const switchedFrom = useRef(page) // also makes StrictMode's second effect run a no-op
  useEffect(() => {
    document.title = TITLES[page]
    if (switchedFrom.current === page) return
    switchedFrom.current = page
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' })
    if (!focusAfterNav.current) return
    focusAfterNav.current = false
    if (page === 'puzzles' && state.kind === 'result' && nextRef.current) {
      nextRef.current.focus({ preventScroll: true })
      return
    }
    // PlayPage's own effect (a child, so it ran first) has focused Next hand when the hand is over
    const active = document.activeElement
    if (
      page === 'play' &&
      active instanceof HTMLElement &&
      active.dataset.primaryFocus !== undefined
    )
      return
    const heading = {
      puzzles: puzzlesHeadingRef,
      play: playHeadingRef,
      progress: titleRef,
      settings: titleRef,
    }[page]
    heading.current?.focus({ preventScroll: true })
  }, [page, state.kind])

  // Replay or Result over a puzzle that is on screen and unanswered asks first (the puzzle would be
  // replaced). Opening is ignored while a load or a submit is in flight: then stay on Progress.
  const [pendingOpen, setPendingOpen] = useState<{ kind: 'puzzle' | 'attempt'; id: number } | null>(
    null,
  )
  const openNow = (target: { kind: 'puzzle' | 'attempt'; id: number }) => {
    const opened =
      target.kind === 'puzzle' ? flow.openPuzzle(target.id) : flow.openAttempt(target.id)
    if (opened) navigate('puzzles')
  }
  const requestOpen = (target: { kind: 'puzzle' | 'attempt'; id: number }) => {
    if (state.kind === 'answering') setPendingOpen(target)
    else openNow(target)
  }

  // End session: a running hand is given up, so that asks first; between hands it ends at once.
  // During the reveal the hand is already complete on the server (nothing is lost), so that ends
  // at once too, rather than claiming Villain takes the pot.
  const [confirmEnd, setConfirmEnd] = useState(false)
  const handRunning = play.session?.hand != null && play.session.hand.status !== 'complete'
  const requestEnd = () => {
    if (play.busy) return
    if (handRunning) setConfirmEnd(true)
    else play.end()
  }

  const onNewPuzzle = () => {
    if (state.kind === 'answering') flow.requestSkip()
    else flow.newPuzzle()
  }

  const attemptId = result?.attempt.id ?? null
  const explained = useExplanation(
    attemptId,
    result?.explanation ?? null,
    (signal) => client.getExplanation(attemptId!, signal),
    settings,
  )
  const showPotOdds = settings?.show_pot_odds ?? true
  const showProfile = settings?.show_profile ?? true

  return (
    <div className={styles.app}>
      <TopBar
        page={page}
        onNavigate={goTo}
        street={flow.street}
        onStreet={flow.setStreet}
        profile={settings?.profile ?? null}
        profiles={settings?.profiles ?? []}
        onProfile={(profile) => flow.setSetting({ profile })}
        shortcutsOn={shortcutsOn}
        onHelp={() => setHelpOpen(true)}
        onNewPuzzle={onNewPuzzle}
        tally={play.session ? tallyText(shownTally(play.session, play.revealing)) : null}
        onEndSession={requestEnd}
        endBusy={play.busy}
      />

      <div className={styles.toasts}>
        {onPuzzles && state.kind === 'error' && (
          <div className={styles.banner} role="alert" data-tone="danger">
            <span>{state.message}</span>
            <Button size="sm" onClick={state.retry}>
              Retry
            </Button>
          </div>
        )}
        {onPlay && play.state.kind === 'error' && (
          <div className={styles.banner} role="alert" data-tone="danger">
            <span>{play.state.message}</span>
            <Button size="sm" onClick={play.state.retry}>
              Retry
            </Button>
          </div>
        )}
        {flow.notice !== null && (
          <div className={styles.banner} role="alert" data-tone="warning">
            <span>{flow.notice}</span>
            <Button size="sm" onClick={flow.dismissNotice}>
              Dismiss
            </Button>
          </div>
        )}
        {onPuzzles && skipPending && (
          <div className={styles.banner} role="status" data-tone="info">
            <span>
              Skip this puzzle? Press <kbd className={styles.kbd}>N</kbd> again
            </span>
            <Button size="sm" onClick={flow.requestSkip}>
              Skip
            </Button>
            <Button size="sm" onClick={flow.cancelSkip}>
              Cancel
            </Button>
          </div>
        )}
      </div>

      {page === 'progress' && (
        <main className={styles.progress}>
          <ProgressPage
            api={progressApi}
            profiles={settings?.profiles ?? null}
            titleRef={titleRef}
            onNavigate={goTo}
            onReplay={(id) => requestOpen({ kind: 'puzzle', id })}
            onResult={(attemptId) => requestOpen({ kind: 'attempt', id: attemptId })}
          />
        </main>
      )}

      {page === 'settings' && (
        <main className={styles.progress}>
          <SettingsPage
            settings={settings}
            settingsError={flow.settingsError}
            onRetry={flow.reloadSettings}
            onSetting={flow.setSetting}
            onCheckLlm={flow.checkLlm}
            shortcutsOn={shortcutsOn}
            onShortcutsOn={setShortcutsOn}
            onShowShortcuts={() => setHelpOpen(true)}
            headingRef={titleRef}
          />
        </main>
      )}

      {/* hidden, not unmounted, on the other pages: a half-entered answer survives the visit */}
      <main className={layout.main} aria-busy={pending || undefined} hidden={!onPuzzles}>
        <h2 className={styles.srOnly} ref={puzzlesHeadingRef} tabIndex={-1}>
          Puzzles
        </h2>
        {view === null ? (
          <div className={styles.empty} role="status">
            {state.kind === 'error' ? 'No puzzle loaded' : 'Dealing…'}
          </div>
        ) : (
          <>
            <div className={`${layout.top} ${styles.play}`} data-pending={pending || undefined}>
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
                    dealFrom={runOut ? view.board.length : 0}
                    // after a fold the board keeps its own deal timing, or a changed delay could
                    // replay the animation on cards already dealt
                    dealBaseMs={runOut ? RUNOUT_BASE_MS : BOARD_DEAL_BASE_MS}
                    dealStaggerMs={runOut ? RUNOUT_STAGGER_MS : BOARD_DEAL_STAGGER_MS}
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
              resetKey={view.id}
              className={layout.side}
            />
            {result && (
              <div
                className={`${layout.details} ${styles.details}`}
                data-pending={pending || undefined}
              >
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
                      onNavigate={goTo}
                    />
                  }
                  handTab={<HandReveal view={view} result={result} />}
                />
              </div>
            )}
          </>
        )}
      </main>

      {/* hidden, not unmounted, like Puzzles: the session and the bot's reveal go on */}
      <PlayPage
        flow={play}
        settings={settings}
        shortcutsOn={playKeysOn}
        onNavigate={goTo}
        headingRef={playHeadingRef}
        hidden={!onPlay}
      />

      {/* always mounted, so screen readers announce the verdict when its text arrives */}
      <div className={styles.srOnly} role="status" aria-live="polite" data-testid="announcer">
        {state.kind === 'result'
          ? `${VERDICT_LABELS[state.result.grade.verdict]}. ${verdictLine(state.result)}`
          : ''}
      </div>

      {pendingOpen !== null && (
        <ConfirmDialog
          title="Leave this puzzle?"
          body="The puzzle on the Puzzles page hasn't been answered. Open this one instead?"
          confirmLabel="Open"
          cancelLabel="Cancel"
          onCancel={() => setPendingOpen(null)}
          onConfirm={() => {
            setPendingOpen(null)
            openNow(pendingOpen)
          }}
        />
      )}

      {confirmEnd && (
        <ConfirmDialog
          title="End this session?"
          body="The hand in progress is given up and Villain takes the pot."
          confirmLabel="End session"
          cancelLabel="Keep playing"
          onCancel={() => setConfirmEnd(false)}
          onConfirm={() => {
            setConfirmEnd(false)
            play.end()
          }}
        />
      )}

      <ShortcutsOverlay open={helpOpen} page={page} onClose={() => setHelpOpen(false)} />
    </div>
  )
}
