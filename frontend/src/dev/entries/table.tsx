import type { CSSProperties, ReactNode } from 'react'
import { Card } from '../../components/Card/Card'
import { Table } from '../../components/Table/Table'
import { formatBb, formatPct } from '../../lib/format'
import { SEAT_SLOTS, seatsFromView, type SeatInfo } from '../../lib/seats'
import { puzzleFixture } from '../../test/fixture'
import type { GalleryEntry } from '../Gallery'

const RANKS = '23456789TJQKA'.split('')
const SUITS = ['s', 'h', 'd', 'c']

const row: CSSProperties = { display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }
const caption: CSSProperties = {
  margin: 'var(--space-5) 0 var(--space-2)',
  color: 'var(--color-text-muted)',
  fontSize: 'var(--text-sm)',
}

/**
 * A stand-in for the table centre (Task 3 builds the real one). It fills the whole centre budget
 * documented in Table.module.css (22em × 10em, outlined here), so the gallery shows that
 * nothing on the table reaches it.
 */
function DemoCentre({
  board,
  pot,
  potOdds,
}: {
  board: string[]
  pot: number
  potOdds: number | null
}) {
  const slots = [...board, ...Array<null>(5 - board.length).fill(null)]
  return (
    <div
      data-centre-budget=""
      style={{
        display: 'grid',
        alignContent: 'center',
        justifyItems: 'center',
        gap: '0.6em',
        width: '22em',
        height: '10em',
        outline: '1px dashed var(--color-felt-line)',
        borderRadius: 'var(--radius-md)',
      }}
    >
      <div style={{ display: 'flex', gap: '0.4em' }}>
        {slots.map((card, i) => (
          <Card key={i} card={card} size="md" />
        ))}
      </div>
      <div
        style={{
          fontWeight: 600,
          fontVariantNumeric: 'tabular-nums',
          color: 'var(--color-text-on-felt)',
        }}
      >
        Pot {formatBb(pot)}
      </div>
      {potOdds !== null && (
        <div style={{ color: 'var(--color-text-on-felt-muted)', fontSize: '0.9em' }}>
          Pot odds {formatPct(potOdds)} · needs {formatPct(potOdds)} equity to call
        </div>
      )}
    </div>
  )
}

function Demo({ title, children }: { title: string; children: ReactNode }) {
  return (
    <figure style={{ margin: 'var(--space-6) 0 0' }}>
      <figcaption style={caption}>{title}</figcaption>
      {children}
    </figure>
  )
}

function fixtureTable(name: string, opts: { showProfile: boolean; villainCards?: string[] }) {
  const view = puzzleFixture(name)
  return (
    <Table
      seats={seatsFromView(view, opts)}
      centre={<DemoCentre board={view.board} pot={view.pot} potOdds={view.pot_odds} />}
    />
  )
}

const FIVE_SEATS: SeatInfo[] = SEAT_SLOTS.filter((slot) => slot !== 'top').map((slot, i) => ({
  slot,
  name: i === 0 ? 'Hero' : ['Ana', 'Ben', 'Chloé', 'Dmitri'][i - 1]!,
  position: ['CO', 'BTN', 'SB', 'BB', 'UTG'][i]!,
  stackChips: [135, 200, 175, 0, 200][i]!,
  betChips: [60, 0, 1, 26, 0][i]!,
  isHero: i === 0,
  isButton: i === 1,
  cards: i === 0 ? ['Qs', 'Jh'] : [null, null],
  faceDown: i !== 0,
  profile: i === 0 ? undefined : { label: 'TAG', description: 'Tight-aggressive: solid ranges.' },
  showProfile: i !== 0,
}))

const fiveCentre = <DemoCentre board={['9h', '8d', '2c']} pot={64} potOdds={0.25} />

const entry: GalleryEntry = {
  title: 'Cards and table',
  render: () => (
    <div>
      <p style={caption}>Every card (md)</p>
      <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
        {SUITS.map((s) => (
          <div key={s} style={row}>
            {RANKS.map((r) => (
              <Card key={r} card={r + s} />
            ))}
          </div>
        ))}
      </div>

      <p style={caption}>Sizes sm / md / lg, face down, empty slot, dealt with a stagger</p>
      <div style={{ ...row, alignItems: 'flex-end', gap: 'var(--space-4)' }}>
        <Card card="Ah" size="sm" />
        <Card card="Ah" size="md" />
        <Card card="Ah" size="lg" />
        <Card card={null} faceDown size="sm" />
        <Card card={null} faceDown size="md" />
        <Card card={null} faceDown size="lg" />
        <Card card={null} size="lg" />
        {['Tc', 'Td', 'Ts'].map((c, i) => (
          <Card key={c} card={c} size="lg" dealDelayMs={150 + i * 120} />
        ))}
      </div>

      <Demo title="Heads-up, pre-flop: Hero BB facing an open (profile shown)">
        {fixtureTable('preflop_bb_facing_open', { showProfile: true })}
      </Demo>
      <Demo title="Heads-up, pre-flop: Hero on the button facing a 3-bet">
        {fixtureTable('preflop_facing_3bet', { showProfile: true })}
      </Demo>
      <Demo title="Heads-up, river: Villain revealed, profile hidden">
        {fixtureTable('river', { showProfile: false, villainCards: ['Ah', 'Qh'] })}
      </Demo>
      <Demo title="Heads-up, river: facing an all-in">
        {fixtureTable('facing_all_in', { showProfile: true })}
      </Demo>
      <Demo title="Five seats (synthetic)">
        <Table seats={FIVE_SEATS} centre={fiveCentre} />
      </Demo>
    </div>
  ),
}

export default entry
