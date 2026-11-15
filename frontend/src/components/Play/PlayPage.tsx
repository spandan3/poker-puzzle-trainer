import { useEffect, useRef, useState } from 'react'
import type { CustomSizes, PlayHandView, SettingsView } from '../../api/types'
import type { PlayFlow } from '../../app/usePlayFlow'
import {
  BOARD_DEAL_BASE_MS,
  BOARD_DEAL_STAGGER_MS,
  HOLE_DEAL_MS,
  HOLE_STAGGER_MS,
} from '../../lib/dealTiming'
import { seatsFromView } from '../../lib/seats'
import { tableAt, toActAt } from '../../lib/play'
import type { Command } from '../../lib/shortcuts'
import { useShortcuts } from '../../lib/shortcuts'
import { AnswerPanel } from '../AnswerPanel/AnswerPanel'
import { HistoryPanel } from '../HistoryPanel/HistoryPanel'
import { Table } from '../Table/Table'
import { TableCentre } from '../TableCentre/TableCentre'
import { HandOverPanel } from './HandOverPanel'
import { StartPanel } from './StartPanel'
import styles from './Play.module.css'

export interface PlayPageProps {
  flow: PlayFlow
  /** the settings the Puzzles flow loaded (one source for the whole app) */
  settings: Pick<SettingsView, 'show_profile' | 'show_pot_odds'> | null
  /** single-key shortcuts act on this page now (on, the page is shown, no overlay open) */
  shortcutsOn: boolean
  /** "Analyse this hand" */
  onAnalyse: (handId: number) => void
  /** the page is not on show (it stays mounted) */
  hidden?: boolean
}

const NO_CUSTOM: CustomSizes = { allowed: false, min_to: null, max_to: null }

/** The Play page: the table, the history, and the action, hand-over or start panel. */
export function PlayPage({
  flow,
  settings,
  shortcutsOn,
  onAnalyse,
  hidden = false,
}: PlayPageProps) {
  const { session, shownCount, revealing, busy } = flow
  const hand = session?.hand ?? null
  const showPotOdds = settings?.show_pot_odds ?? true
  const showProfile = settings?.show_profile ?? true
  const handOver = hand !== null && hand.status === 'complete' && !revealing

  // "Top up to 100 bb" is chosen per hand: it resets when the next one is dealt
  const [topUp, setTopUp] = useState(false)
  const [topUpHand, setTopUpHand] = useState<number | null>(null)
  if (topUpHand !== (hand?.id ?? null)) {
    setTopUpHand(hand?.id ?? null)
    setTopUp(false)
  }

  const slotRef = useRef<HTMLDivElement>(null)
  const nextRef = useRef<HTMLButtonElement>(null)

  // Keyboard focus follows the panel: the Next button when the hand ends, else the panel slot
  // (never a text box, which would pause the shortcuts). On a switch to this page it moves here
  // too, as the link that was clicked has just left the page's flow.
  const handIsOver = handOver
  const wasHidden = useRef(hidden)
  useEffect(() => {
    const justShown = wasHidden.current && !hidden
    wasHidden.current = hidden
    if (hidden) return
    if (handIsOver) {
      nextRef.current?.focus({ preventScroll: true })
      return
    }
    const active = document.activeElement
    if (justShown || active === null || active === document.body || !active.isConnected) {
      slotRef.current?.focus({ preventScroll: true })
    }
  }, [hidden, handIsOver, hand?.id])

  const onCommand = (cmd: Command): boolean => {
    if (cmd.id !== 'next' || !handOver || busy) return false
    flow.nextHand(topUp)
    return true
  }
  useShortcuts(onCommand, shortcutsOn && !hidden)

  if (session === null || hand === null) {
    return (
      <main className={styles.main} hidden={hidden} aria-busy={busy || undefined}>
        <div className={styles.startWrap}>
          {flow.state.kind === 'loading' ? (
            <p className={styles.loading} role="status">
              Loading…
            </p>
          ) : (
            <StartPanel onStart={flow.start} busy={busy} past={flow.past} />
          )}
        </div>
      </main>
    )
  }

  const shown = tableAt(hand, shownCount)
  const toAct = toActAt(hand, shownCount)
  // the bot's cards turn over once the reveal is done, at a showdown only
  const villainCards = handOver ? (hand.outcome?.villain_cards ?? undefined) : undefined

  return (
    <main className={styles.main} hidden={hidden} aria-busy={busy || revealing || undefined}>
      <div className={styles.play}>
        <Table
          // a new hand re-mounts the table, so the cards deal in again
          key={hand.id}
          seats={seatsFromView(shown, { showProfile, villainCards }).map((seat) => ({
            ...seat,
            dealDelaysMs: HOLE_DEAL_MS.map((ms) => ms + (seat.isHero ? 0 : HOLE_STAGGER_MS)),
            flip: villainCards !== undefined && !seat.isHero,
          }))}
          centre={
            <TableCentre
              board={shown.board}
              potChips={shown.pot}
              potOdds={shown.pot_odds}
              showPotOdds={showPotOdds}
              dealFrom={0}
              dealBaseMs={BOARD_DEAL_BASE_MS}
              dealStaggerMs={BOARD_DEAL_STAGGER_MS}
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
              onAnalyse={onAnalyse}
              shortcutsOn={shortcutsOn}
              topUp={topUp}
              onTopUp={setTopUp}
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
      </div>
      <HistoryPanel view={shown} toAct={toAct} className={styles.side} />
    </main>
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
