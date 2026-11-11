import styles from './ChipStack.module.css'

/** How many chips to draw for a bet: grows slowly with its size, one to five. */
export function chipCount(chips: number): number {
  const bb = chips / 2
  if (bb <= 1) return 1
  return Math.min(5, 1 + Math.ceil(Math.log2(bb) / 1.5))
}

const RX = 11
const RY = 4.2
const SIDE = 3
const STEP = 3.6

/** A small stack of chips, seen from slightly above. Decorative: the amount is shown as text. */
export function ChipStack({ chips }: { chips: number }) {
  const n = chipCount(chips)
  const height = RY * 2 + SIDE + STEP * (n - 1) + 1
  const width = RX * 2 + 2
  return (
    <svg
      className={styles.stack}
      viewBox={`0 0 ${width} ${height}`}
      style={{ aspectRatio: `${width} / ${height}` }}
      aria-hidden="true"
      focusable="false"
    >
      {Array.from({ length: n }, (_, i) => {
        // Bottom chip first, so higher chips are drawn over it.
        const cy = height - RY - SIDE - 0.5 - i * STEP
        const alt = i % 2 === 1
        return (
          <g key={i} className={alt ? styles.alt : styles.main}>
            <path
              className={styles.side}
              d={`M${1} ${cy} v${SIDE} a${RX} ${RY} 0 0 0 ${RX * 2} 0 v${-SIDE} Z`}
            />
            <ellipse className={styles.top} cx={RX + 1} cy={cy} rx={RX} ry={RY} />
            <ellipse className={styles.stripes} cx={RX + 1} cy={cy} rx={RX - 1.6} ry={RY - 0.7} />
            <ellipse className={styles.inlay} cx={RX + 1} cy={cy} rx={RX - 4.6} ry={RY - 1.7} />
          </g>
        )
      })}
    </svg>
  )
}
