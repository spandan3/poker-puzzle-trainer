import { useState } from 'react'
import { chartScale } from '../../lib/stats'
import styles from './Charts.module.css'

export interface Bar {
  label: string
  value: number
}

export interface BarChartProps {
  title: string
  bars: Bar[]
  /** a goal line; bars that reach it are drawn in the accent colour */
  goal: number
  /** the unit for the data table's value heading (default "Puzzles") */
  valueLabel?: string
  /** the x axis name in the data table (default "Day") */
  xLabel?: string
  width?: number
  height?: number
}

const M = { top: 22, right: 8, bottom: 26, left: 30 }

/** Our own bar chart: one bar per label against a dashed goal line, with a data table for screen readers. */
export function BarChart({
  title,
  bars,
  goal,
  valueLabel = 'Puzzles',
  xLabel = 'Day',
  width = 560,
  height = 220,
}: BarChartProps) {
  const [open, setOpen] = useState(false) // the data table's rows exist only while it is open
  const scale = chartScale(Math.max(goal, ...bars.map((b) => b.value)))
  const plotW = width - M.left - M.right
  const plotH = height - M.top - M.bottom
  const slot = bars.length > 0 ? plotW / bars.length : plotW
  const barW = Math.min(slot * 0.62, 56)
  const met = bars.filter((b) => b.value >= goal).length
  const most = Math.max(0, ...bars.map((b) => b.value))
  const sy = (y: number) => M.top + plotH - (y / scale.max) * plotH

  return (
    <figure className={styles.figure}>
      <svg
        className={styles.svg}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${title} (goal ${goal})`}
        data-testid="bar-chart"
      >
        <text className={styles.unit} x={0} y={10}>
          {valueLabel}
        </text>
        {scale.ticks.map((t) => (
          <g key={t}>
            <line
              className={t === 0 ? styles.axis : styles.grid}
              x1={M.left}
              x2={width - M.right}
              y1={sy(t)}
              y2={sy(t)}
            />
            <text className={styles.tick} x={M.left - 6} y={sy(t) + 4} textAnchor="end">
              {t}
            </text>
          </g>
        ))}
        {bars.map((b, i) => {
          const cx = M.left + slot * i + slot / 2
          const top = sy(b.value)
          return (
            <g key={b.label}>
              <rect
                className={styles.bar}
                data-met={b.value >= goal ? '' : undefined}
                x={cx - barW / 2}
                y={top}
                width={barW}
                height={Math.max(sy(0) - top, 0)}
                rx={2}
              />
              {b.value > 0 && (
                <text className={styles.value} x={cx} y={top - 4}>
                  {b.value}
                </text>
              )}
              <text className={styles.tick} x={cx} y={height - 6} textAnchor="middle">
                {b.label}
              </text>
            </g>
          )
        })}
        <line
          className={styles.goalLine}
          data-testid="goal-line"
          x1={M.left}
          x2={width - M.right}
          y1={sy(goal)}
          y2={sy(goal)}
        />
        <text className={styles.goalLabel} x={width - M.right} y={sy(goal) - 5} textAnchor="end">
          Goal {goal}
        </text>
      </svg>
      <p className={styles.srOnly}>
        {met} of {bars.length} days reached the goal of {goal}; most in a day: {most}.
      </p>
      <details
        className={styles.data}
        onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
      >
        <summary>Show data</summary>
        <div className={styles.dataTable}>
          <table>
            <caption>
              {title} (goal {goal} per day)
            </caption>
            <thead>
              <tr>
                <th scope="col">{xLabel}</th>
                <th scope="col">{valueLabel}</th>
              </tr>
            </thead>
            <tbody>
              {(open ? bars : []).map((b) => (
                <tr key={b.label}>
                  <th scope="row">{b.label}</th>
                  <td>{b.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  )
}
