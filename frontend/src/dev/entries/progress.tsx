import type { CSSProperties } from 'react'
import type { ProgressApi } from '../../components/Progress/ProgressPage'
import { ProgressPage } from '../../components/Progress/ProgressPage'
import { LineChart } from '../../components/Charts/LineChart'
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
      <ProgressPage api={withStats(statsFixture)} onReplay={() => {}} onResult={() => {}} />

      <p style={caption}>Line chart: warm-up band and tooltip (hover a point)</p>
      <div style={{ maxWidth: '40rem' }}>
        <LineChart
          title="Gallery trend"
          yLabel="bb"
          format={(y) => `${y.toFixed(2)} bb`}
          warmUp={50}
          width={560}
          series={[
            {
              label: 'EV lost (bb)',
              points: Array.from({ length: 90 }, (_, i) => ({
                x: i + 1,
                y: 1.5 + Math.sin(i / 7) * (i < 50 ? 1.2 : 0.4),
              })),
            },
          ]}
        />
      </div>

      <p style={caption}>Line chart: empty state</p>
      <div style={{ maxWidth: '40rem' }}>
        <LineChart
          title="Gallery empty"
          yLabel="pts"
          format={(y) => `${y} pts`}
          empty="No range reads yet. Answer a puzzle with a range read to start this chart."
          series={[{ label: 'A', points: [{ x: 1, y: null }] }]}
        />
      </div>

      <p style={caption}>Nothing answered yet (stats_empty.json)</p>
      <ProgressPage api={withStats(statsEmptyFixture)} onReplay={() => {}} onResult={() => {}} />
    </div>
  ),
}

export default entry
