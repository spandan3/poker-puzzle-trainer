import type { TrendPoint } from '../../api/types'
import { LineChart } from '../Charts/LineChart'
import { Panel } from '../ui'
import { formatEvBb } from '../../lib/format'
import { rollingWindowOf } from '../../lib/stats'
import styles from './Progress.module.css'

export interface TrendChartsProps {
  trend: TrendPoint[]
  /** the API's `rolling_window`: first attempts each point averages; points before it average fewer and read as noise */
  rollingWindow: number
}

/** A value already in percentage points (the series are fractions x 100). */
const formatPoints = (points: number) => `${points.toFixed(1)} pts`

/** The EV-lost trend (full width), then equity error and range-read error side by side; all are rolling means over the API's window. */
export function TrendCharts({ trend, rollingWindow }: TrendChartsProps) {
  // a payload without the window gets no band and no number, never "rolling undefined"
  const n = rollingWindowOf(rollingWindow)
  const rolling = n === null ? '' : `, rolling ${n} puzzles`
  const warmUp = n ?? undefined
  return (
    <section aria-labelledby="trend-title" className={styles.section}>
      <h3 id="trend-title" className={styles.sectionTitle}>
        Trends
      </h3>
      <p className={styles.hint}>
        {n === null
          ? 'Each point is a rolling average of your first attempts up to that puzzle.'
          : `Each point averages your last ${n} first attempts up to that puzzle.`}
      </p>
      <Panel title="EV lost per decision" headingLevel={4}>
        <LineChart
          title={`EV lost per decision${rolling}`}
          yLabel="bb"
          format={formatEvBb}
          width={900}
          height={240}
          warmUp={warmUp}
          series={[
            {
              label: 'EV lost (bb)',
              points: trend.map((p) => ({ x: p.n, y: p.ev_lost_bb_avg })),
            },
          ]}
        />
      </Panel>
      <div className={styles.pair}>
        <Panel title="Equity error" headingLevel={4}>
          <LineChart
            title={`Equity error${rolling}`}
            yLabel="pts"
            format={formatPoints}
            width={420}
            height={220}
            warmUp={warmUp}
            series={[
              {
                label: 'Equity error (pts)',
                points: trend.map((p) => ({ x: p.n, y: p.equity_error_avg * 100 })),
              },
            ]}
          />
        </Panel>
        <Panel title="Range-read error" headingLevel={4}>
          <LineChart
            title={`Range-read error${rolling}`}
            yLabel="pts"
            format={formatPoints}
            width={420}
            height={220}
            warmUp={warmUp}
            empty="No range reads yet. Answer a puzzle with a range read to start this chart."
            series={[
              {
                label: 'Range-read error (pts)',
                points: trend.map((p) => ({
                  x: p.n,
                  y: p.range_read_error_avg === null ? null : p.range_read_error_avg * 100,
                })),
              },
            ]}
          />
        </Panel>
      </div>
    </section>
  )
}
