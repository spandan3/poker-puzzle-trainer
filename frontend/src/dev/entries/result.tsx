import type { CSSProperties, ReactNode } from 'react'
import type { AttemptResult } from '../../api/types'
import { HistoryPanel } from '../../components/HistoryPanel/HistoryPanel'
import { ResultStrip } from '../../components/ResultStrip/ResultStrip'
import { Table } from '../../components/Table/Table'
import { TableCentre } from '../../components/TableCentre/TableCentre'
import { answerEntry } from '../../lib/result'
import { seatsFromView } from '../../lib/seats'
import { attemptFixture, puzzleFixture } from '../../test/fixture'
import type { GalleryEntry } from '../Gallery'

const caption: CSSProperties = {
  margin: 'var(--space-5) 0 var(--space-2)',
  color: 'var(--color-text-muted)',
  fontSize: 'var(--text-sm)',
}

function Demo({ title, children }: { title: string; children: ReactNode }) {
  return (
    <figure style={{ margin: 'var(--space-6) 0 0' }}>
      <figcaption style={caption}>{title}</figcaption>
      {children}
    </figure>
  )
}

function variant(result: AttemptResult, grade: Partial<AttemptResult['grade']>): AttemptResult {
  return { ...result, grade: { ...result.grade, ...grade } }
}

const bet = attemptFixture('bet')
const fold = attemptFixture('fold')
const flop = puzzleFixture('flop_unopened')

const entry: GalleryEntry = {
  title: 'Result strip',
  render: () => (
    <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
      <Demo title="Revealed table and history (flop, bet 33%)">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 18rem', gap: 'var(--space-4)' }}>
          <Table
            seats={seatsFromView(flop, {
              showProfile: true,
              villainCards: bet.reveal.villain_cards,
            })}
            centre={
              <TableCentre
                board={bet.reveal.runout}
                potChips={flop.pot}
                potOdds={flop.pot_odds}
                showPotOdds
              />
            }
          />
          <HistoryPanel view={flop} answer={answerEntry(flop, bet)} />
        </div>
      </Demo>
      <Demo title="Best (the top play)">
        <ResultStrip result={bet} onNext={() => {}} shortcutsOn />
      </Demo>
      <Demo title="Fine (close to the top play)">
        <ResultStrip
          result={variant(bet, { verdict: 'fine', ev_loss_bb: 0.11, best_label: 'bet 75%' })}
          onNext={() => {}}
          shortcutsOn
        />
      </Demo>
      <Demo title="Mistake (pre-flop fold)">
        <ResultStrip result={fold} onNext={() => {}} shortcutsOn />
      </Demo>
      <Demo title="Blunder, loading the next puzzle, shortcuts off">
        <ResultStrip
          result={variant(fold, { verdict: 'blunder', ev_loss_bb: 6.4 })}
          onNext={() => {}}
          shortcutsOn={false}
          loading
        />
      </Demo>
    </div>
  ),
}

export default entry
