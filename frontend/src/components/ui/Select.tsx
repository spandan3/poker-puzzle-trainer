import { useId } from 'react'
import type { ReactNode } from 'react'
import styles from './ui.module.css'

export interface SelectProps {
  label: string
  value: string
  onChange: (value: string) => void
  /** The `<option>` elements. */
  children: ReactNode
  id?: string
  disabled?: boolean
}

/** A native `<select>` with a visible label, styled with the app's controls. */
export function Select({ label, value, onChange, children, id, disabled }: SelectProps) {
  const auto = useId()
  const selectId = id ?? auto
  return (
    <div className={styles.field}>
      <label htmlFor={selectId} className={styles.fieldLabel}>
        {label}
      </label>
      <span className={styles.selectWrap}>
        <select
          id={selectId}
          className={styles.select}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          {children}
        </select>
        <svg className={styles.chevron} viewBox="0 0 12 12" aria-hidden="true">
          <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </span>
    </div>
  )
}
