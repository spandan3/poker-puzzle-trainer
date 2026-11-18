import { useState } from 'react'
import type { MouseEvent } from 'react'
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
  /** shown in place of the chart when no point has a value */
  empty?: string
  /** points with x below this sit on a shaded band ("Fewer than N puzzles") */
  warmUp?: number
  /** the pointer tooltip's text (default "Puzzle n · rolling average: value") */
  tooltipLabel?: (x: number, y: number) => string
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
  empty,
  warmUp,
  tooltipLabel,
}: LineChartProps) {
  // the data table's rows exist only while it is open (a 500-row table would otherwise sit in the DOM)
  const [open, setOpen] = useState(false)
  // the point under the pointer (a pointer aid only: keyboard users have the data table)
  const [hover, setHover] = useState<{ x: number; y: number; series: number } | null>(null)
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

  if (empty !== undefined && ys.length === 0) {
    return (
      <figure className={styles.figure}>
        <p className={styles.empty} role="status">
          {empty}
        </p>
      </figure>
    )
  }

  const warmUpOn = warmUp !== undefined && xs.length > 0 && xMin < warmUp
  const warmUpRight = warmUp === undefined ? 0 : sx(Math.min(warmUp, xMax))
  const tip =
    tooltipLabel ?? ((x: number, y: number) => `${xLabel} ${x} · rolling average: ${format(y)}`)

  // the nearest point by x, from the pointer's place in the SVG's own coordinates
  const onMove = (event: MouseEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    if (box.width === 0) return
    const px = ((event.clientX - box.left) / box.width) * width
    let best: { x: number; y: number; series: number } | null = null
    series.forEach((s, i) => {
      for (const p of s.points) {
        if (p.y === null) continue
        if (best === null || Math.abs(sx(p.x) - px) < Math.abs(sx(best.x) - px)) {
          best = { x: p.x, y: p.y, series: i }
        }
      }
    })
    setHover(best)
  }

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
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {warmUpOn && (
          <g data-testid="warm-up">
            <rect
              className={styles.warmUp}
              x={M.left}
              y={M.top}
              width={Math.max(warmUpRight - M.left, 0)}
              height={plotH}
            />
            <text className={styles.warmUpLabel} x={M.left + 4} y={M.top + 12}>
              Fewer than {warmUp} puzzles
            </text>
          </g>
        )}
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
        {hover && (
          <circle
            className={`${styles.hoverDot} ${styles[`s${hover.series % 2}`]}`}
            cx={sx(hover.x)}
            cy={sy(hover.y)}
            r={4.5}
          />
        )}
      </svg>
      {hover && (
        <div
          className={styles.tooltip}
          data-testid="chart-tooltip"
          data-side={sx(hover.x) > width * 0.6 ? 'left' : 'right'}
          aria-hidden="true"
          style={{
            left: `${(sx(hover.x) / width) * 100}%`,
            top: `${(sy(hover.y) / height) * 100}%`,
          }}
        >
          {tip(hover.x, hover.y)}
        </div>
      )}
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
