import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { keyToCommand } from '../../lib/shortcuts'
import { Button } from './Button'
import styles from './ui.module.css'

export interface ConfirmDialogProps {
  title: string
  body: ReactNode
  confirmLabel: string
  cancelLabel: string
  onConfirm: () => void
  onCancel: () => void
}

/**
 * A modal `<dialog>`, open while mounted. Focus goes to the cancel button and returns to the
 * opener on close. Keys are isolated here, as in `ShortcutsOverlay`: while open, a capture
 * listener on `window` stops every key before the page's listeners see it. Tab passes, so the
 * browser's own modal focus trap works. Escape cancels.
 */
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const onCancelRef = useRef(onCancel)
  useEffect(() => {
    onCancelRef.current = onCancel
  })

  useEffect(() => {
    const dialog = dialogRef.current
    const previous = document.activeElement
    if (dialog && !dialog.open) dialog.showModal()
    cancelRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Tab') return
      event.stopImmediatePropagation()
      if (event.key === 'Escape') {
        event.preventDefault()
        onCancelRef.current()
      } else if (keyToCommand(event, { enabled: true })) {
        event.preventDefault()
      }
    }
    window.addEventListener('keydown', onKeyDown, true)
    return () => {
      window.removeEventListener('keydown', onKeyDown, true)
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [])

  return (
    <dialog
      ref={dialogRef}
      className={styles.dialog}
      aria-labelledby={titleId}
      onCancel={(e) => {
        // the close goes through onCancel, so the owner decides
        e.preventDefault()
        onCancel()
      }}
    >
      <h2 id={titleId} className={styles.dialogTitle}>
        {title}
      </h2>
      <div className={styles.dialogBody}>{body}</div>
      <div className={styles.dialogActions}>
        <Button ref={cancelRef} variant="secondary" onClick={onCancel}>
          {cancelLabel}
        </Button>
        <Button variant="primary" onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  )
}
