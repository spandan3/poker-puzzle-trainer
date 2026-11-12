import type { TrendPoint } from '../../api/types'
import { LineChart } from '../Charts/LineChart'
import { bb1 } from '../../lib/stats'
import styles from './Progress.module.css'

export interface TrendChartsProps {
  trend: TrendPoint[]
}

const ptsOf = (fraction: number) => `${fraction.toFixed(1)} pts`

/** The EV-lost trend (full width), then equity error and range-read error side by side; all are rolling means over 50 puzzles. */
export function TrendCharts({ trend }: TrendChartsProps) {
  return (
    <section aria-labelledby="trend-title" className={styles.section}>
      <h2 id="trend-title" className={styles.h2}>
        Trends
      </h2>
      <p className={styles.hint}>
        Each point averages your last 50 first attempts up to that puzzle.
      </p>
      <div className={styles.card}>
        <h3 className={styles.h3}>EV lost per decision</h3>
        <LineChart
          title="EV lost per decision, rolling 50 puzzles"
          yLabel="bb"
          format={bb1}
          width={1120}
          height={260}
          series={[
            {
              label: 'EV lost (bb)',
              points: trend.map((p) => ({ x: p.n, y: p.ev_lost_bb_avg })),
            },
          ]}
        />
      </div>
      <div className={styles.pair}>
        <div className={styles.card}>
          <h3 className={styles.h3}>Equity error</h3>
          <LineChart
            title="Equity error, rolling 50 puzzles"
            yLabel="pts"
            format={ptsOf}
            series={[
              {
                label: 'Equity error (pts)',
                points: trend.map((p) => ({ x: p.n, y: p.equity_error_avg * 100 })),
              },
            ]}
          />
        </div>
        <div className={styles.card}>
          <h3 className={styles.h3}>Range-read error</h3>
          <LineChart
            title="Range-read error, rolling 50 puzzles"
            yLabel="pts"
            format={ptsOf}
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
        </div>
      </div>
    </section>
  )
}
