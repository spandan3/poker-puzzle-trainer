import type { ButtonHTMLAttributes, MouseEvent, ReactNode, Ref } from 'react'
import styles from './ui.module.css'

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  variant?: 'primary' | 'secondary' | 'ghost'
  size?: 'sm' | 'md'
  /** A key hint (rendered `aria-hidden`); the caller sets `aria-keyshortcuts`. */
  kbd?: string
  /** Work in progress: `aria-disabled` (focus stays) and clicks are ignored. */
  busy?: boolean
  ref?: Ref<HTMLButtonElement>
  children: ReactNode
}

export function Button({
  variant = 'secondary',
  size = 'md',
  kbd,
  busy = false,
  className,
  onClick,
  type = 'button',
  children,
  ...rest
}: ButtonProps) {
  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    if (busy) {
      event.preventDefault()
      return
    }
    onClick?.(event)
  }
  return (
    <button
      {...rest}
      type={type}
      className={[styles.button, className].filter(Boolean).join(' ')}
      data-variant={variant}
      data-size={size}
      aria-disabled={busy ? true : undefined}
      onClick={handleClick}
    >
      {children}
      {kbd !== undefined && (
        <kbd className={styles.kbd} aria-hidden="true">
          {kbd}
        </kbd>
      )}
    </button>
  )
}
