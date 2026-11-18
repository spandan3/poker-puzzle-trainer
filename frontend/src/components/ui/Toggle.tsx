import { useId } from 'react'
import styles from './ui.module.css'

export interface ToggleProps {
  label: string
  on: boolean
  onChange: (on: boolean) => void
  /** A line under the label, linked as the switch's description. */
  description?: string
}

/** A switch (`role="switch"`): Enter or Space flips it. */
export function Toggle({ label, on, onChange, description }: ToggleProps) {
  const descId = useId()
  const labelId = useId()
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-labelledby={labelId}
      aria-describedby={description ? descId : undefined}
      className={styles.toggle}
      onClick={() => onChange(!on)}
    >
      <span className={styles.track} aria-hidden="true">
        <span className={styles.thumb} />
      </span>
      <span className={styles.toggleText}>
        <span id={labelId}>{label}</span>
        {description && (
          <span id={descId} className={styles.toggleDesc}>
            {description}
          </span>
        )}
      </span>
    </button>
  )
}
