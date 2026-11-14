import { useState } from 'react'
import { chartScale } from '../../lib/stats'
import styles from './Charts.module.css'

export interface LinePoint {
  x: number
  /** `null` leaves a gap in the line */
  y: number | null
}

export interface LineSeries {
  label: string
  points: LinePoint[]
}

export interface LineChartProps {
  /** what the chart shows: its accessible name */
  title: string
  series: LineSeries[]
  /** the unit, drawn above the axis and used as the data table's value heading */
  yLabel: string
  /** a value as text: the last value's label and the data table */
  format: (y: number) => string
  /** the x axis name in the data table (default "Puzzle") */
  xLabel?: string
  /** the SVG's own coordinate size (text scales with the chart: the wider the chart, the larger this) */
  width?: number
  height?: number
}

const M = { top: 22, right: 64, bottom: 26, left: 40 }

/** Our own line chart: y from 0, x by number, gridlines, the last value labelled, and a data table for screen readers. */
export function LineChart({
  title,
  series,
  yLabel,
  format,
  xLabel = 'Puzzle',
  width = 560,
  height = 240,
}: LineChartProps) {
  // the data table's rows exist only while it is open (a 500-row table would otherwise sit in the DOM)
  const [open, setOpen] = useState(false)
  const all = series.flatMap((s) => s.points)
  const xs = all.map((p) => p.x)
  const xMin = xs.length > 0 ? Math.min(...xs) : 0
  const xMax = xs.length > 0 ? Math.max(...xs) : 1
  const ys = all.flatMap((p) => (p.y === null ? [] : [p.y]))
  const scale = chartScale(ys.length > 0 ? Math.max(...ys) : 0)

  const plotW = width - M.left - M.right
  const plotH = height - M.top - M.bottom
  const sx = (x: number) =>
    M.left + (xMax === xMin ? plotW / 2 : ((x - xMin) / (xMax - xMin)) * plotW)
  const sy = (y: number) => M.top + plotH - (y / scale.max) * plotH

  // about five x labels, whole numbers
  const xTicks: number[] = []
  if (xs.length > 0) {
    const span = xMax - xMin
    const n = Math.min(5, span + 1)
    for (let i = 0; i < n; i++) {
      xTicks.push(n === 1 ? xMin : Math.round(xMin + (span * i) / (n - 1)))
    }
  }

  const pathOf = (points: LinePoint[]): string => {
    let d = ''
    let pen = false
    for (const p of points) {
      if (p.y === null) {
        pen = false
        continue
      }
      d += `${pen ? 'L' : 'M'}${sx(p.x).toFixed(1)} ${sy(p.y).toFixed(1)}`
      pen = true
    }
    return d
  }

  // one sentence per series for screen readers: where it started, ended and peaked
  const summary = series
    .map((s) => {
      const vals = s.points.flatMap((p) => (p.y === null ? [] : [p.y]))
      if (vals.length === 0) return `${s.label}: no data.`
      return `${s.label}: first ${format(vals[0]!)}, last ${format(vals[vals.length - 1]!)}, lowest ${format(Math.min(...vals))}, highest ${format(Math.max(...vals))}.`
    })
    .join(' ')

  // the data table: one row per x, one column per series
  const rows = [...new Set(xs)].sort((a, b) => a - b)
  const lookup = series.map((s) => new Map(s.points.map((p) => [p.x, p.y])))

  return (
    <figure className={styles.figure}>
      {series.length > 1 && (
        <ul className={styles.legend} aria-hidden="true">
          {series.map((s, i) => (
            <li key={s.label} className={styles[`s${i % 2}`]}>
              {s.label}
            </li>
          ))}
        </ul>
      )}
      <svg
        className={styles.svg}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={title}
        data-testid="line-chart"
      >
        <text className={styles.unit} x={0} y={10}>
          {yLabel}
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
        {xTicks.map((t) => (
          <text key={t} className={styles.tick} x={sx(t)} y={height - 6} textAnchor="middle">
            {t}
          </text>
        ))}
        {series.map((s, i) => {
          const last = [...s.points].reverse().find((p) => p.y !== null)
          return (
            <g key={s.label} className={styles[`s${i % 2}`]}>
              <path className={styles.line} d={pathOf(s.points)} data-series={s.label} />
              {last && last.y !== null && (
                <>
                  <circle className={styles.dot} cx={sx(last.x)} cy={sy(last.y)} r={3.5} />
                  <text className={styles.last} x={sx(last.x) + 8} y={sy(last.y) + 4}>
                    {format(last.y)}
                  </text>
                </>
              )}
            </g>
          )
        })}
      </svg>
      <p className={styles.srOnly}>{summary}</p>
      <details
        className={styles.data}
        onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
      >
        <summary>Show data</summary>
        <div className={styles.dataTable}>
          <table>
            <caption>{title}</caption>
            <thead>
              <tr>
                <th scope="col">{xLabel}</th>
                {series.map((s) => (
                  <th key={s.label} scope="col">
                    {series.length > 1 ? `${s.label} (${yLabel})` : yLabel}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(open ? rows : []).map((x) => (
                <tr key={x}>
                  <th scope="row">{x}</th>
                  {lookup.map((m, i) => {
                    const y = m.get(x)
                    return (
                      <td key={series[i]!.label}>
                        {y === undefined || y === null ? '—' : format(y)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  )
}
