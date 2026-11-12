import { useId, type CSSProperties } from 'react'
import { cardName, parseCard, rankGlyph } from '../../lib/cards'
import styles from './Card.module.css'
import { SuitShape } from './suits'

export type CardSize = 'sm' | 'md' | 'lg'

export interface CardProps {
  /** A card code such as "Th", or `null` for an unknown card (an empty slot unless face down). */
  card: string | null
  faceDown?: boolean
  size?: CardSize
  /** Delay before the deal-in animation; no animation when omitted. */
  dealDelayMs?: number
  /** Turn face up with a flip (Villain's cards on reveal). */
  flip?: boolean
  className?: string
}

// The card is drawn in a 100×140 box (5:7, the poker-card ratio).
const W = 100
const H = 140
const RADIUS = 8

export function Card({
  card,
  faceDown = false,
  size = 'md',
  dealDelayMs,
  flip = false,
  className,
}: CardProps) {
  const dealing = dealDelayMs !== undefined
  const common = {
    className: [styles.card, className].filter(Boolean).join(' '),
    'data-size': size,
    'data-dealing': dealing ? 'true' : undefined,
    'data-flip': flip && !faceDown && card !== null ? 'true' : undefined,
    style: dealing ? ({ animationDelay: `${dealDelayMs}ms` } as CSSProperties) : undefined,
  }

  if (faceDown) {
    return (
      <span {...common} role="img" aria-label="face-down card" data-face="down">
        <CardBack />
      </span>
    )
  }

  if (card === null) {
    return (
      <span {...common} aria-hidden="true" data-face="empty">
        <svg viewBox={`0 0 ${W} ${H}`} className={styles.svg} focusable="false">
          <rect className={styles.slot} x="2" y="2" width={W - 4} height={H - 4} rx={RADIUS} />
        </svg>
      </span>
    )
  }

  const { rank, suit } = parseCard(card)
  const colour = suit === 'h' || suit === 'd' ? 'red' : 'black'
  const glyph = rankGlyph(rank)
  return (
    <span
      {...common}
      role="img"
      aria-label={cardName(card)}
      data-face="up"
      data-suit={suit}
      data-rank={rank}
      data-colour={colour}
    >
      <svg viewBox={`0 0 ${W} ${H}`} className={styles.svg} focusable="false" aria-hidden="true">
        <rect
          className={styles.face}
          x="0.75"
          y="0.75"
          width={W - 1.5}
          height={H - 1.5}
          rx={RADIUS}
        />
        <g className={styles.ink}>
          <Corner glyph={glyph} suit={suit} />
          <g transform={`rotate(180 ${W / 2} ${H / 2})`}>
            <Corner glyph={glyph} suit={suit} />
          </g>
          <svg x="28" y="48" width="44" height="44" viewBox="0 0 100 100">
            <SuitShape suit={suit} />
          </svg>
        </g>
      </svg>
    </span>
  )
}

function Corner({ glyph, suit }: { glyph: string; suit: ReturnType<typeof parseCard>['suit'] }) {
  const wide = glyph.length > 1
  return (
    <g>
      <text
        className={styles.rank}
        x="17"
        y="31"
        textAnchor="middle"
        fontSize={wide ? 26 : 30}
        letterSpacing={wide ? -2.5 : 0}
      >
        {glyph}
      </text>
      <svg x="7" y="37" width="20" height="20" viewBox="0 0 100 100">
        <SuitShape suit={suit} />
      </svg>
    </g>
  )
}

function CardBack() {
  const patternId = `card-back-${useId().replace(/[^\w-]/g, '')}`
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={styles.svg} focusable="false" aria-hidden="true">
      <defs>
        <pattern
          id={patternId}
          width="10"
          height="10"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <path className={styles.backLattice} d="M0 0 H10 M0 0 V10" />
          <circle className={styles.backDot} cx="5" cy="5" r="1.2" />
        </pattern>
      </defs>
      <rect
        className={styles.backFrame}
        x="0.75"
        y="0.75"
        width={W - 1.5}
        height={H - 1.5}
        rx={RADIUS}
      />
      <rect className={styles.backField} x="7" y="7" width={W - 14} height={H - 14} rx="4" />
      <rect x="7" y="7" width={W - 14} height={H - 14} rx="4" fill={`url(#${patternId})`} />
      <rect
        className={styles.backInnerLine}
        x="11"
        y="11"
        width={W - 22}
        height={H - 22}
        rx="2.5"
      />
      <path className={styles.backEmblem} d="M50 52 L66 70 L50 88 L34 70 Z" />
      <path className={styles.backEmblemInner} d="M50 61 L58 70 L50 79 L42 70 Z" />
    </svg>
  )
}
