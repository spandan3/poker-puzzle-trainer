import { useEffect, useId, useRef } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import type { Page } from '../../lib/page'
import type { ShortcutGroup } from '../../lib/shortcuts'
import { SHORTCUTS, describeShortcut, isOnPage, keyToCommand } from '../../lib/shortcuts'
import styles from './ShortcutsOverlay.module.css'

export interface ShortcutsOverlayProps {
  open: boolean
  /** The page the keys act on (default Puzzles): Play lists no guess shortcuts. */
  page?: Page
  onClose: () => void
}

const GROUPS: ShortcutGroup[] = ['Answer', 'Action', 'Size', 'Intent', 'Puzzle']

/**
 * The keyboard shortcuts, listed from `SHORTCUTS`. A modal dialog drawn without
 * `<dialog>.showModal`: Escape, the close button or a click outside closes it, focus moves to
 * the close button on open and returns where it was on close.
 */
export function ShortcutsOverlay({ open, page = 'puzzles', onClose }: ShortcutsOverlayProps) {
  const titleId = useId()
  const closeRef = useRef<HTMLButtonElement>(null)
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement
    closeRef.current?.focus()
    // While open, no key reaches the page behind: every key but Tab (which the dialog traps)
    // stops here, and keys that would be a shortcut lose their default too. Native activation of
    // the Close button (Enter, Space) still works.
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Tab') return
      event.stopImmediatePropagation()
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
      } else if (keyToCommand(event, { enabled: true })) {
        event.preventDefault()
      }
    }
    // capture on window: runs before any page listener, including the shortcut hooks
    window.addEventListener('keydown', onKeyDown, true)
    return () => {
      window.removeEventListener('keydown', onKeyDown, true)
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [open])

  if (!open) return null

  // keep Tab inside the dialog: the close button is its only control
  const trapTab = (event: ReactKeyboardEvent) => {
    if (event.key === 'Tab') {
      event.preventDefault()
      closeRef.current?.focus()
    }
  }

  return (
    <div
      className={styles.backdrop}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={trapTab}
      >
        <header className={styles.header}>
          <h2 id={titleId} className={styles.title}>
            Keyboard shortcuts
          </h2>
          <button ref={closeRef} type="button" className={styles.close} onClick={onClose}>
            Close
            <kbd className={styles.kbd} aria-hidden="true">
              Esc
            </kbd>
          </button>
        </header>
        <div className={styles.groups}>
          {GROUPS.map((group) => {
            const rows = SHORTCUTS.filter((s) => s.group === group && isOnPage(s.id, page))
            if (rows.length === 0) return null
            return (
              <section key={group} className={styles.group} aria-label={group}>
                <h3 className={styles.groupTitle}>{group}</h3>
                <dl className={styles.list}>
                  {rows.map((s) => (
                    <div key={s.id} className={styles.row} data-shortcut-row={s.id}>
                      <dt className={styles.keys}>
                        {s.keysLabel ? (
                          <kbd className={styles.kbd}>{s.keysLabel}</kbd>
                        ) : (
                          s.keys.map((k, i) => (
                            <span key={k} className={styles.alt}>
                              {i > 0 && <span className={styles.or}>or</span>}
                              <kbd className={styles.kbd}>{k}</kbd>
                            </span>
                          ))
                        )}
                      </dt>
                      <dd className={styles.description}>{describeShortcut(s.id, page)}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )
          })}
        </div>
        <p className={styles.footnote}>
          Shortcuts pause while you type in a box; press Esc to leave it. Turn them off with the
          Shortcuts toggle.
        </p>
      </div>
    </div>
  )
}
