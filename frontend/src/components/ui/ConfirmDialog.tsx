import { useEffect, useId, useRef, useState } from 'react'
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
 *
 * Every key but Tab is stopped at the window, so a text box inside the body would get no React
 * `onKeyDown` (its `onChange` still works); add a way through if a dialog ever needs one.
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
  const bodyId = useId()
  // the opener, read once at the first render: StrictMode runs the effect twice, and by the
  // second run focus has moved into the dialog
  const [opener] = useState(() => document.activeElement)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const onCancelRef = useRef(onCancel)
  useEffect(() => {
    onCancelRef.current = onCancel
  })

  useEffect(() => {
    const dialog = dialogRef.current
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
      // close first: while the modal is open the opener is inert and refuses focus. (The effect
      // reopens it on StrictMode's second run.)
      if (dialog?.open) dialog.close()
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [opener])

  return (
    <dialog
      ref={dialogRef}
      className={styles.dialog}
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      onCancel={(e) => {
        // the close goes through onCancel, so the owner decides
        e.preventDefault()
        onCancel()
      }}
    >
      <h2 id={titleId} className={styles.dialogTitle}>
        {title}
      </h2>
      <div id={bodyId} className={styles.dialogBody}>
        {body}
      </div>
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
