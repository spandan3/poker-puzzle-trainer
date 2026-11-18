import type { ProfileInfo, StreetName } from '../../api/types'
import { STREET_LABELS, STREET_ORDER } from '../../lib/history'
import type { Page } from '../../lib/page'
import { isPlainLeftClick, pathOf } from '../../lib/page'
import { shortcut } from '../../lib/shortcuts'
import { Button, Select } from '../ui'
import styles from './TopBar.module.css'

const NAV: { page: Page; label: string }[] = [
  { page: 'puzzles', label: 'Puzzles' },
  { page: 'play', label: 'Play' },
  { page: 'progress', label: 'Progress' },
]

export interface TopBarProps {
  /** the page on show: the puzzle controls appear on Puzzles only, the session controls on Play */
  page: Page
  onNavigate: (page: Page) => void
  /** The street for new puzzles; `null` is "Any street". */
  street: StreetName | null
  onStreet: (street: StreetName | null) => void
  /** The Villain profile key; `null` is "Random". */
  profile: string | null
  profiles: Pick<ProfileInfo, 'name' | 'label'>[]
  onProfile: (profile: string | null) => void
  /** whether single-key shortcuts are on: the key hints show (the switch itself is in Settings) */
  shortcutsOn: boolean
  onHelp: () => void
  onNewPuzzle: () => void
  /** Play: the session's tally (`+12.5 bb · 14 hands`), or null with no open session. */
  tally: string | null
  onEndSession: () => void
  /** a play request is in flight: End session waits (`aria-disabled`, with a title saying why) */
  endBusy?: boolean
}

function isStreet(x: string): x is StreetName {
  return (STREET_ORDER as readonly string[]).includes(x)
}

export function TopBar(props: TopBarProps) {
  const hintAttrs = (id: 'help' | 'next') =>
    props.shortcutsOn && props.page !== 'progress'
      ? { 'data-shortcut': id, 'aria-keyshortcuts': shortcut(id).aria }
      : {}
  const onPuzzles = props.page === 'puzzles'
  const onPlay = props.page === 'play'
  // Progress and Settings have no puzzle controls and no shortcuts of their own
  const onProgress = props.page === 'progress' || props.page === 'settings'
  const onSettings = props.page === 'settings'
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
            <Select
              label="Street"
              value={props.street ?? ''}
              onChange={(value) => props.onStreet(isStreet(value) ? value : null)}
            >
              <option value="">Any street</option>
              {STREET_ORDER.map((st) => (
                <option key={st} value={st}>
                  {STREET_LABELS[st]}
                </option>
              ))}
            </Select>

            <Select
              label="Villain"
              value={props.profile ?? ''}
              onChange={(value) => props.onProfile(value === '' ? null : value)}
            >
              <option value="">Random</option>
              {props.profiles.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.label}
                </option>
              ))}
            </Select>
          </>
        )}

        {onPlay && props.tally !== null && (
          <>
            <span className={styles.tabularNums} aria-label="Session tally">
              {props.tally}
            </span>
            <Button
              size="sm"
              busy={props.endBusy}
              title={props.endBusy ? 'Wait for the hand to update' : undefined}
              onClick={props.onEndSession}
            >
              End session
            </Button>
          </>
        )}

        {/* shortcuts are off on Progress, so there is nothing to show help for */}
        {!onProgress && (
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
          <Button
            variant="primary"
            kbd={props.shortcutsOn ? 'N' : undefined}
            onClick={props.onNewPuzzle}
            {...hintAttrs('next')}
          >
            New puzzle
          </Button>
        )}
      </div>

      <a
        href={pathOf('settings')}
        className={styles.settingsLink}
        aria-label="Settings"
        title="Settings"
        aria-current={onSettings ? 'page' : undefined}
        onClick={(e) => {
          if (!isPlainLeftClick(e)) return
          e.preventDefault()
          props.onNavigate('settings')
        }}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
          <path
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-2.5.1-.5-.1-.5 1.9-1.5-1.9-3.3-2.3.8a7.6 7.6 0 0 0-.9-.5L15.8 4h-3.7l-.4 2.5c-.3.1-.6.3-.9.5l-2.3-.8-1.9 3.3 1.9 1.5-.1.5.1.5-1.9 1.5 1.9 3.3 2.3-.8c.3.2.6.4.9.5l.4 2.5h3.7l.4-2.5c.3-.1.6-.3.9-.5l2.3.8 1.9-3.3-1.9-1.5Z"
          />
        </svg>
      </a>
    </header>
  )
}
