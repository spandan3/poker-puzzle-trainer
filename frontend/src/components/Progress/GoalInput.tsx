import { useId, useState } from 'react'
import type { KeyboardEvent } from 'react'
import styles from './GoalInput.module.css'

export const GOAL_MIN = 1
export const GOAL_MAX = 500

export interface GoalInputProps {
  /** the goal setting, shown in the box */
  goal: number
  /** saves the goal; resolves true when it was saved */
  onGoal: (goal: number) => Promise<boolean>
}

/** "Puzzles per day": a whole number from 1 to 500, committed on Enter or blur. */
export function GoalInput({ goal, onGoal }: GoalInputProps) {
  const inputId = useId()
  const errorId = useId()
  const [draft, setDraft] = useState(String(goal))
  const [seen, setSeen] = useState(goal)
  const [error, setError] = useState<string | null>(null)
  if (seen !== goal) {
    // the goal changed from outside (a save, a refetch): the box follows
    setSeen(goal)
    setDraft(String(goal))
    setError(null)
  }

  const commit = () => {
    const text = draft.trim()
    const n = Number(text)
    if (text === '' || !Number.isInteger(n) || n < GOAL_MIN || n > GOAL_MAX) {
      setError(`Enter a whole number from ${GOAL_MIN} to ${GOAL_MAX}`)
      return
    }
    setError(null)
    if (n === goal) return
    // a failed save reverts the setting, and the box follows it back
    void onGoal(n)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      commit()
    }
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.field}>
        <label htmlFor={inputId} className={styles.label}>
          Puzzles per day
        </label>
        <input
          id={inputId}
          type="number"
          inputMode="numeric"
          min={GOAL_MIN}
          max={GOAL_MAX}
          step={1}
          className={styles.number}
          value={draft}
          aria-invalid={error !== null || undefined}
          aria-describedby={error !== null ? errorId : undefined}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={onKeyDown}
        />
      </div>
      {error !== null && (
        <p id={errorId} className={styles.error} role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
