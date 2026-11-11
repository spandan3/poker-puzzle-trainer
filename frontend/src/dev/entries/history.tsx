import { useState, type CSSProperties } from 'react'
import { HistoryPanel } from '../../components/HistoryPanel/HistoryPanel'
import { Table } from '../../components/Table/Table'
import { TableCentre } from '../../components/TableCentre/TableCentre'
import { TopBar } from '../../components/TopBar/TopBar'
import type { StreetName } from '../../api/types'
import { seatsFromView } from '../../lib/seats'
import { puzzleFixture, settingsFixture } from '../../test/fixture'
import type { GalleryEntry } from '../Gallery'

const caption: CSSProperties = {
  margin: 'var(--space-5) 0 var(--space-2)',
  color: 'var(--color-text-muted)',
  fontSize: 'var(--text-sm)',
}

const layout: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 20rem), 1fr))',
  gap: 'var(--space-4)',
  alignItems: 'start',
}

function TableWithHistory({ name }: { name: string }) {
  const view = puzzleFixture(name)
  return (
    <div style={layout}>
      <div style={{ gridColumn: 'span 2', minWidth: 0 }}>
        <Table
          seats={seatsFromView(view, { showProfile: true })}
          centre={
            <TableCentre
              board={view.board}
              potChips={view.pot}
              potOdds={view.pot_odds}
              showPotOdds
            />
          }
        />
      </div>
      <HistoryPanel view={view} />
    </div>
  )
}

function InteractiveTopBar() {
  const settings = settingsFixture()
  const [street, setStreet] = useState<StreetName | null>(null)
  const [profile, setProfile] = useState<string | null>(null)
  const [potOdds, setPotOdds] = useState(true)
  const [showProfile, setShowProfile] = useState(false)
  const [shortcuts, setShortcuts] = useState(true)
  return (
    <TopBar
      street={street}
      onStreet={setStreet}
      profile={profile}
      profiles={settings.profiles}
      onProfile={setProfile}
      showPotOdds={potOdds}
      onShowPotOdds={setPotOdds}
      showProfile={showProfile}
      onShowProfile={setShowProfile}
      shortcutsOn={shortcuts}
      onShortcutsOn={setShortcuts}
      onHelp={() => undefined}
      onNewPuzzle={() => undefined}
    />
  )
}

const entry: GalleryEntry = {
  title: 'History and table centre',
  render: () => (
    <div>
      <p style={caption}>Top bar</p>
      <InteractiveTopBar />

      <p style={caption}>Turn, 3-bet pot, Villain jams (history beside the table)</p>
      <TableWithHistory name="history_3bet_and_all_in" />

      <p style={caption}>Unopened flop: empty decision street</p>
      <TableWithHistory name="flop_unopened" />

      <p style={caption}>Pre-flop, BB facing an open</p>
      <TableWithHistory name="preflop_bb_facing_open" />

      <p style={caption}>River, facing an all-in</p>
      <TableWithHistory name="facing_all_in" />

      <p style={caption}>Panel on its own, flop facing a raise</p>
      <div style={{ maxWidth: '24rem' }}>
        <HistoryPanel view={puzzleFixture('facing_postflop_raise')} />
      </div>
    </div>
  ),
}

export default entry
