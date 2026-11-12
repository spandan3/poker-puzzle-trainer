import { useEffect, useId, useState } from 'react'
import { formatBb } from '../../lib/format'
import type { SeatInfo, SeatProfile } from '../../lib/seats'
import { Card } from '../Card/Card'
import { ChipStack } from './ChipStack'
import styles from './Seat.module.css'

export interface SeatProps {
  seat: SeatInfo
  className?: string
}

export function Seat({ seat, className }: SeatProps) {
  const allIn = seat.stackChips === 0
  const profile = seat.showProfile ? seat.profile : undefined
  return (
    <div
      className={[styles.seat, className].filter(Boolean).join(' ')}
      role="group"
      aria-label={`${seat.name}, ${seat.position}`}
      data-slot={seat.slot}
      data-hero={seat.isHero ? 'true' : undefined}
      data-cards={seat.faceDown ? 'down' : 'up'}
    >
      <div className={styles.cards} data-part="cards">
        {seat.cards.map((card, i) => (
          <Card
            key={i}
            card={card}
            faceDown={seat.faceDown}
            size={seat.isHero ? 'lg' : 'md'}
            dealDelayMs={seat.dealDelaysMs?.[i]}
            flip={seat.flip}
            className={styles.card}
          />
        ))}
      </div>

      <div className={styles.plate}>
        <div className={styles.row}>
          <span className={styles.name}>{seat.name}</span>
          <span className={styles.position}>{seat.position}</span>
        </div>
        <div className={styles.row}>
          {allIn ? (
            <span className={styles.allIn}>
              <span className={styles.srOnly}>Stack 0 bb, </span>All-in
            </span>
          ) : (
            <span key={seat.stackChips} className={styles.stack} data-fade="">
              <span className={styles.srOnly}>Stack </span>
              {formatBb(seat.stackChips)}
            </span>
          )}
          {profile && <ProfileBadge profile={profile} />}
        </div>
        {seat.isButton && (
          <span className={styles.dealer} role="img" aria-label="Dealer button">
            <span aria-hidden="true">D</span>
          </span>
        )}
      </div>

      {seat.betChips > 0 && (
        <div className={styles.bet} data-part="bet">
          <ChipStack chips={seat.betChips} />
          <span className={styles.betAmount}>
            <span className={styles.srOnly}>Bet </span>
            {formatBb(seat.betChips)}
          </span>
        </div>
      )}
    </div>
  )
}

/**
 * Villain's profile label, a button described by a tooltip with the one-line tendency. The
 * tooltip opens on hover or focus, stays open while the pointer is over the badge or the tooltip,
 * and closes on Escape, blur or pointer leave (WCAG 1.4.13).
 */
function ProfileBadge({ profile }: { profile: SeatProfile }) {
  const tooltipId = useId()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <span
      className={styles.profile}
      onPointerEnter={() => setOpen(true)}
      onPointerLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className={styles.profileBadge}
        aria-label={`Profile ${profile.label}`}
        aria-describedby={tooltipId}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        {profile.label}
      </button>
      <span
        className={styles.tooltip}
        role="tooltip"
        id={tooltipId}
        data-state={open ? 'open' : 'closed'}
      >
        {profile.description}
      </span>
    </span>
  )
}
