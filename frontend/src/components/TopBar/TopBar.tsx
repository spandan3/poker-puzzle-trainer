import { useId } from 'react'
import type { ProfileInfo, StreetName } from '../../api/types'
import { STREET_LABELS, STREET_ORDER } from '../../lib/history'
import type { Page } from '../../lib/page'
import { isPlainLeftClick, pathOf } from '../../lib/page'
import { shortcut } from '../../lib/shortcuts'
import styles from './TopBar.module.css'

const NAV: { page: Page; label: string }[] = [
  { page: 'puzzles', label: 'Puzzles' },
  { page: 'progress', label: 'Progress' },
]

export interface TopBarProps {
  /** the page on show: the puzzle controls appear on Puzzles only */
  page: Page
  onNavigate: (page: Page) => void
  /** The street for new puzzles; `null` is "Any street". */
  street: StreetName | null
  onStreet: (street: StreetName | null) => void
  /** The Villain profile key; `null` is "Random". */
  profile: string | null
  profiles: Pick<ProfileInfo, 'name' | 'label'>[]
  onProfile: (profile: string | null) => void
  showPotOdds: boolean
  onShowPotOdds: (on: boolean) => void
  showProfile: boolean
  onShowProfile: (on: boolean) => void
  shortcutsOn: boolean
  onShortcutsOn: (on: boolean) => void
  onHelp: () => void
  onNewPuzzle: () => void
}

function isStreet(x: string): x is StreetName {
  return (STREET_ORDER as readonly string[]).includes(x)
}

export function TopBar(props: TopBarProps) {
  const hintAttrs = (id: 'help' | 'next') =>
    props.shortcutsOn && props.page === 'puzzles'
      ? { 'data-shortcut': id, 'aria-keyshortcuts': shortcut(id).aria }
      : {}
  const streetId = useId()
  const profileId = useId()
  const onPuzzles = props.page === 'puzzles'
  return (
    <header className={styles.bar}>
      <h1 className={styles.title}>
        <span className={styles.mark} aria-hidden="true">
          ♠
        </span>
        <span className={styles.titleText}>Poker Puzzle Trainer</span>
      </h1>

      <nav aria-label="Main" className={styles.nav}>
        {NAV.map(({ page, label }) => (
          <a
            key={page}
            href={pathOf(page)}
            className={styles.navLink}
            aria-current={props.page === page ? 'page' : undefined}
            onClick={(e) => {
              if (!isPlainLeftClick(e)) return
              e.preventDefault()
              props.onNavigate(page)
            }}
          >
            {label}
          </a>
        ))}
      </nav>

      <div className={styles.controls}>
        {onPuzzles && (
          <>
            <div className={styles.field}>
              <label htmlFor={streetId}>Street</label>
              <select
                id={streetId}
                className={styles.select}
                value={props.street ?? ''}
                onChange={(e) => props.onStreet(isStreet(e.target.value) ? e.target.value : null)}
              >
                <option value="">Any street</option>
                {STREET_ORDER.map((s) => (
                  <option key={s} value={s}>
                    {STREET_LABELS[s]}
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.field}>
              <label htmlFor={profileId}>Villain</label>
              <select
                id={profileId}
                className={styles.select}
                value={props.profile ?? ''}
                onChange={(e) => props.onProfile(e.target.value === '' ? null : e.target.value)}
              >
                <option value="">Random</option>
                {props.profiles.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.toggles}>
              <Toggle label="Pot odds" on={props.showPotOdds} onChange={props.onShowPotOdds} />
              <Toggle label="Show profile" on={props.showProfile} onChange={props.onShowProfile} />
              <Toggle label="Shortcuts" on={props.shortcutsOn} onChange={props.onShortcutsOn} />
            </div>
          </>
        )}

        {/* shortcuts are off on Progress, so there is nothing to show help for */}
        {onPuzzles && (
          <button
            type="button"
            className={styles.help}
            aria-label="Keyboard shortcuts help"
            onClick={props.onHelp}
            {...hintAttrs('help')}
          >
            {/* the glyph is the button's key hint */}
            <kbd className={styles.helpGlyph} aria-hidden="true">
              ?
            </kbd>
          </button>
        )}
        {onPuzzles && (
          <button
            type="button"
            className={styles.primary}
            onClick={props.onNewPuzzle}
            {...hintAttrs('next')}
          >
            New puzzle
            {props.shortcutsOn && (
              <kbd className={styles.kbd} aria-hidden="true">
                N
              </kbd>
            )}
          </button>
        )}
      </div>
    </header>
  )
}

function Toggle({
  label,
  on,
  onChange,
}: {
  label: string
  on: boolean
  onChange: (on: boolean) => void
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      className={styles.toggle}
      onClick={() => onChange(!on)}
    >
      <span className={styles.track} aria-hidden="true">
        <span className={styles.thumb} />
      </span>
      {label}
    </button>
  )
}
