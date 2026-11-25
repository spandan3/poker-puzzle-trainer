import { forwardRef, useEffect, useRef, useState } from 'react'
import type { Ref } from 'react'
import * as client from '../../api/client'
import type { CustomSizes, PlayHandView, SettingsView, TableView } from '../../api/types'
import type { PlayFlow } from '../../app/usePlayFlow'
import {
  BOARD_DEAL_BASE_MS,
  BOARD_DEAL_STAGGER_MS,
  HOLE_DEAL_MS,
  HOLE_STAGGER_MS,
} from '../../lib/dealTiming'
import type { Page } from '../../lib/page'
import { seatLogAt } from '../../lib/history'
import type { SeatInfo } from '../../lib/seats'
import { seatsFromPlayTable, seatsFromView } from '../../lib/seats'
import { heroFolded, shownTally, tableAt, toActAt } from '../../lib/play'
import type { Command } from '../../lib/shortcuts'
import { useShortcuts } from '../../lib/shortcuts'
import { AnswerPanel } from '../AnswerPanel/AnswerPanel'
import { HistoryPanel } from '../HistoryPanel/HistoryPanel'
import { Table } from '../Table/Table'
import { TableCentre } from '../TableCentre/TableCentre'
import { Button, Panel } from '../ui'
import { HandAnalysis } from './HandAnalysis'
import type { HandAnalysisApi } from './HandAnalysis'
import { HandOverPanel } from './HandOverPanel'
import type { SessionHandsApi } from './SessionHands'
import { SessionHands } from './SessionHands'
import { StartPanel } from './StartPanel'
import styles from './Play.module.css'
import layout from '../../styles/tableLayout.module.css'

export type PlayPageApi = HandAnalysisApi & SessionHandsApi

export interface PlayPageProps {
  flow: PlayFlow
  /** the settings the Puzzles flow loaded (one source for the whole app) */
  settings: Pick<
    SettingsView,
    'show_profile' | 'show_pot_odds' | 'show_range' | 'llm_status' | 'llm_model' | 'llm_detail'
  > | null
  /** single-key shortcuts act on this page now (on, the page is shown, no overlay open) */
  shortcutsOn: boolean
  /** the analysis and hand-list requests (the real client by default; a fake in tests) */
  api?: PlayPageApi
  /** the page heading, so the app can focus it after a nav-link click */
  headingRef?: Ref<HTMLHeadingElement>
  /** the analysis's "Settings" link */
  onNavigate?: (page: Page) => void
  /** the page is not on show (it stays mounted) */
  hidden?: boolean
  /** the page's root element: `main` in the app, `div` where it sits inside another `main` */
  as?: 'main' | 'div'
}

const NO_CUSTOM: CustomSizes = { allowed: false, min_to: null, max_to: null }

/** The Play page: the table, the history, and the action, hand-over or start panel. */
export function PlayPage({
  flow,
  settings,
  shortcutsOn,
  api = client,
  onNavigate,
  headingRef,
  hidden = false,
  as: Root = 'main',
}: PlayPageProps) {
  const { session, shownCount, revealing, busy } = flow
  const hand = session?.hand ?? null
  const showPotOdds = settings?.show_pot_odds ?? true
  const showProfile = settings?.show_profile ?? true
  const handOver = hand !== null && hand.status === 'complete' && !revealing
  // 5-max, Hero has folded and the bots are still playing the hand out: Next hand is on offer
  // (and skips the rest), where the heads-up flow always waits for the reveal
  const skippable =
    hand !== null &&
    hand.status === 'complete' &&
    revealing &&
    hand.table.table_size === 5 &&
    heroFolded(hand.table.history)

  // "Top up to 100 bb" is chosen per hand: it resets when the next one is dealt
  const [topUp, setTopUp] = useState(false)
  const [topUpHand, setTopUpHand] = useState<number | null>(null)
  if (topUpHand !== (hand?.id ?? null)) {
    setTopUpHand(hand?.id ?? null)
    setTopUp(false)
  }

  // the hand whose analysis is open (a hand of this session or of a past one), and the hand list
  const [analysing, setAnalysing] = useState<number | null>(null)
  const [handsOpen, setHandsOpen] = useState(false)
  const [closedCount, setClosedCount] = useState(0)
  // the table at the step picked in the analysis: the Action panel shows it (never the current hand)
  const [analysisView, setAnalysisView] = useState<TableView | null>(null)
  // the control that opened the analysis: with no session (nothing else to focus) it gets focus back
  const openerRef = useRef<Element | null>(null)
  const openAnalysis = (handId: number) => {
    openerRef.current = document.activeElement
    setAnalysisView(null)
    setAnalysing(handId)
  }
  const closeAnalysis = () => {
    setAnalysing(null)
    setAnalysisView(null)
    setClosedCount((n) => n + 1) // a hand may have been analysed: its row changes
  }
  const analysis = analysing !== null && (
    <>
      <div className={layout.top}>
        <HandAnalysis
          handId={analysing}
          api={api}
          settings={settings}
          onNavigate={onNavigate}
          onClose={closeAnalysis}
          onView={setAnalysisView}
        />
      </div>
      {analysisView !== null && (
        <HistoryPanel
          view={analysisView}
          toAct="hero"
          resetKey={`${analysing}:${analysisView.history.length}`}
          className={layout.side}
        />
      )}
    </>
  )

  const slotRef = useRef<HTMLDivElement>(null)
  const nextRef = useRef<HTMLButtonElement>(null)

  // Keyboard focus follows the panel: the Next button when the hand ends, else the panel slot
  // (never a text box, which would pause the shortcuts). On a switch to this page it moves here
  // too, as the link that was clicked has just left the page's flow.
  const handIsOver = handOver || skippable
  const noSession = session === null
  const wasHidden = useRef(hidden)
  const wasSkippable = useRef(skippable)
  useEffect(() => {
    const justShown = wasHidden.current && !hidden
    wasHidden.current = hidden
    if (hidden) return
    // a playout that has just ended: Next hand takes focus only from nowhere (the button that
    // had it is gone), never from a control the player moved to
    const playoutEnded = wasSkippable.current && !skippable
    wasSkippable.current = skippable
    if (handIsOver && nextRef.current) {
      const focused = document.activeElement
      const free = focused === null || focused === document.body || !focused.isConnected
      if (!playoutEnded || free) nextRef.current.focus({ preventScroll: true })
      return
    }
    const active = document.activeElement
    if (justShown || active === null || active === document.body || !active.isConnected) {
      if (slotRef.current) {
        slotRef.current.focus({ preventScroll: true })
        return
      }
      // no hand on the table (the Start screen, or the session just ended): back to the control
      // that opened the analysis, else the page heading
      const opener = openerRef.current
      // (a mouse click in Safari or Firefox on macOS focuses no button, so the opener is the body)
      if (
        analysing === null &&
        opener instanceof HTMLElement &&
        opener !== document.body &&
        opener.isConnected &&
        !opener.closest('[hidden]')
      ) {
        opener.focus({ preventScroll: true })
      } else if (analysing === null) {
        document.querySelector<HTMLElement>('[data-play-heading]')?.focus({ preventScroll: true })
      }
    }
  }, [hidden, handIsOver, handOver, skippable, hand?.id, analysing, noSession])

  const onCommand = (cmd: Command): boolean => {
    if (cmd.id !== 'next' || !(handOver || skippable) || analysing !== null || busy) return false
    flow.nextHand(topUp)
    return true
  }
  useShortcuts(onCommand, shortcutsOn && !hidden)

  // visually hidden: the table needs the height, but every page has an h2
  const heading = (
    <h2 className={styles.srOnly} ref={headingRef} data-play-heading tabIndex={-1}>
      Play
    </h2>
  )

  if (session === null || hand === null) {
    return (
      <Root className={layout.main} hidden={hidden} aria-busy={busy || undefined}>
        {heading}
        {flow.state.kind === 'loading' ? (
          <div className={styles.startWrap}>
            <p className={styles.loading} role="status">
              Loading…
            </p>
          </div>
        ) : (
          // hidden, not unmounted, while an analysis is open: the open list stays open
          <div className={styles.startWrap} hidden={analysing !== null}>
            <StartPanel
              onStart={flow.start}
              busy={busy}
              past={flow.past}
              onOpenHand={openAnalysis}
              api={api}
              refreshKey={closedCount}
            />
          </div>
        )}
        {analysis}
      </Root>
    )
  }

  const shown = tableAt(hand, shownCount)
  const toAct = toActAt(hand, shownCount)
  const fiveMax = hand.table.table_size === 5
  const total = hand.table.history.length
  // who takes the pot shows only once the reveal is over (the whole history is on screen), so
  // the label never gives the result away; until then it is the frame's "Pot x bb"
  const award =
    !fiveMax && handOver && shownCount >= total && hand.outcome
      ? { winner: hand.outcome.winner, potChips: hand.table.pot }
      : undefined
  // the bot's cards turn over once the reveal is done, at a showdown only
  const villainCards = handOver ? (hand.outcome?.villain_cards ?? undefined) : undefined

  let seats: SeatInfo[]
  if (fiveMax) {
    // Before the last action the seats are drawn from that frame, bots face down. At the end
    // the settled table shows (no frame), and a finished hand turns the shown seats over.
    const frame = shownCount < total ? hand.frames[shownCount] : undefined
    seats = seatsFromPlayTable(shown, {
      showProfile,
      frame,
      revealed: handOver,
    }).map((seat, i) => ({
      ...seat,
      dealDelaysMs: HOLE_DEAL_MS.map((ms) => ms + (seat.isHero ? 0 : HOLE_STAGGER_MS * i)),
    }))
  } else {
    seats = seatsFromView(shown, { showProfile, villainCards }).map((seat) => ({
      ...seat,
      dealDelaysMs: HOLE_DEAL_MS.map((ms) => ms + (seat.isHero ? 0 : HOLE_STAGGER_MS)),
      flip: villainCards !== undefined && !seat.isHero,
    }))
  }
  // the pots as they stand (main, then side pots), from the frame; a settled hand shows its total
  const pots = fiveMax && !handOver ? hand.frames[Math.min(shownCount, total)]?.pots : undefined
  const seatLog = fiveMax
    ? seatLogAt(hand.table, hand.frames, hand.table.history, shownCount)
    : undefined

  return (
    <Root
      className={layout.main}
      hidden={hidden}
      aria-busy={busy || (revealing && !skippable) || undefined}
    >
      {heading}
      {analysing !== null ? (
        analysis
      ) : (
        <>
          <div className={layout.top}>
            <Table
              // a new hand re-mounts the table, so the cards deal in again
              key={hand.id}
              seats={seats}
              centre={
                <TableCentre
                  board={shown.board}
                  potChips={shown.pot}
                  pots={pots}
                  potOdds={shown.pot_odds}
                  showPotOdds={showPotOdds}
                  dealFrom={0}
                  dealBaseMs={BOARD_DEAL_BASE_MS}
                  dealStaggerMs={BOARD_DEAL_STAGGER_MS}
                  award={award}
                />
              }
            />
            <div ref={slotRef} className={styles.slot} tabIndex={-1} aria-label="Action">
              {handOver ? (
                <HandOverPanel
                  ref={nextRef}
                  hand={hand}
                  mustRebuy={session.must_rebuy}
                  canTopUp={session.can_top_up}
                  busy={busy}
                  onNext={flow.nextHand}
                  onAnalyse={openAnalysis}
                  shortcutsOn={shortcutsOn}
                  topUp={topUp}
                  onTopUp={setTopUp}
                />
              ) : skippable ? (
                <PlayingOutPanel
                  ref={nextRef}
                  mustRebuy={session.must_rebuy}
                  busy={busy}
                  onNext={() => flow.nextHand(false)}
                  shortcutsOn={shortcutsOn}
                />
              ) : (
                <ActionSlot
                  hand={hand}
                  shown={shown}
                  revealing={revealing}
                  busy={busy}
                  flow={flow}
                  shortcutsOn={shortcutsOn}
                />
              )}
            </div>
            <Panel
              title="This session"
              flush
              className={styles.sessionHands}
              actions={
                <Button
                  size="sm"
                  aria-expanded={handsOpen}
                  onClick={() => setHandsOpen((open) => !open)}
                >
                  Session hands · {shownTally(session, revealing).hands_played}
                </Button>
              }
            >
              {handsOpen && (
                <div className={styles.handsBody}>
                  <SessionHands
                    sessionId={session.id}
                    api={api}
                    onOpen={openAnalysis}
                    refreshKey={`${hand.id}:${handOver ? 'over' : 'running'}:${closedCount}`}
                    // during the reveal the finished hand reads "In progress", as on the table
                    inProgressId={revealing ? hand.id : undefined}
                  />
                </div>
              )}
            </Panel>
          </div>
          <HistoryPanel view={shown} toAct={toAct} seatLog={seatLog} className={layout.side} />
        </>
      )}
    </Root>
  )
}

function ActionSlot({
  hand,
  shown,
  revealing,
  busy,
  flow,
  shortcutsOn,
}: {
  hand: PlayHandView
  shown: ReturnType<typeof tableAt>
  revealing: boolean
  busy: boolean
  flow: PlayFlow
  shortcutsOn: boolean
}) {
  // while the bot's actions are shown there is no menu: every button is disabled
  const view = revealing
    ? { ...shown, options: [], custom: NO_CUSTOM }
    : { ...shown, options: hand.options, custom: hand.custom }
  return (
    <AnswerPanel
      view={view}
      guesses={false}
      draftKey={`${hand.id}:${hand.action_count}`}
      onAct={flow.act}
      busy={busy || revealing}
      error={null}
      customDisabledReason={null}
      shortcutsOn={shortcutsOn}
    />
  )
}

/**
 * In place of the action panel at a 5-max table once Hero has folded and the bots are still
 * playing: Next hand skips what is left of the hand.
 */
const PlayingOutPanel = forwardRef<
  HTMLButtonElement,
  {
    mustRebuy: boolean
    busy: boolean
    onNext: () => void
    shortcutsOn: boolean
  }
>(function PlayingOutPanel({ mustRebuy, busy, onNext, shortcutsOn }, ref) {
  return (
    <section className={styles.over} aria-label="You folded">
      <p className={styles.result} role="status">
        You folded
      </p>
      <p className={styles.hands}>The bots are playing the hand out.</p>
      <div className={styles.actions}>
        <Button
          ref={ref}
          variant="primary"
          busy={busy}
          kbd={shortcutsOn ? 'N' : undefined}
          data-primary-focus=""
          onClick={onNext}
          {...(shortcutsOn ? { 'data-shortcut': 'next', 'aria-keyshortcuts': 'N' } : {})}
        >
          {mustRebuy ? 'Rebuy and deal' : 'Next hand'}
        </Button>
      </div>
    </section>
  )
})
