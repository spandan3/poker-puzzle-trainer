import type { CSSProperties } from 'react'
import type { ProgressApi } from '../../components/Progress/ProgressPage'
import { ProgressPage } from '../../components/Progress/ProgressPage'
import { historyFixture, statsEmptyFixture, statsFixture } from '../../test/fixture'
import type { GalleryEntry } from '../Gallery'

const caption: CSSProperties = {
  margin: 'var(--space-5) 0 var(--space-2)',
  color: 'var(--color-text-muted)',
  fontSize: 'var(--text-sm)',
}

const withStats = (stats: () => ReturnType<typeof statsFixture>): ProgressApi => ({
  getStats: async () => stats(),
  getHistory: async () => historyFixture(),
})

const entry: GalleryEntry = {
  title: 'Progress',
  render: () => (
    <div>
      <p style={caption}>With 105 puzzles answered (stats.json)</p>
      <ProgressPage api={withStats(statsFixture)} goal={null} onGoal={async () => true} />

      <p style={caption}>Nothing answered yet (stats_empty.json)</p>
      <ProgressPage api={withStats(statsEmptyFixture)} goal={null} onGoal={async () => true} />
    </div>
  ),
}

export default entry
