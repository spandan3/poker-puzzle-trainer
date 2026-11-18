import { useEffect, useRef, useState } from 'react'
import type { Ref } from 'react'
import type { SettingsPatch, SettingsView } from '../../api/types'
import { GoalInput } from '../Progress/GoalInput'
import { Button, Panel, Select, Toggle } from '../ui'
import styles from './Settings.module.css'

export interface SettingsPageProps {
  /** `null` until the first load answers */
  settings: SettingsView | null
  /** the first load failed */
  settingsError: boolean
  onRetry: () => void
  /** saves a change (optimistic; a failed save reverts and the app warns); resolves true when saved */
  onSetting: (patch: SettingsPatch) => Promise<boolean>
  /** re-probes the local model; resolves false when the request failed */
  onCheckLlm: () => Promise<boolean>
  shortcutsOn: boolean
  onShortcutsOn: (on: boolean) => void
  onShowShortcuts: () => void
  /** the page heading, so the app can focus it after a page switch */
  headingRef?: Ref<HTMLHeadingElement>
}

const OFF_TEXT =
  "Explanations come from the trainer's templates. A local model (Ollama) can reword them; see 'Optional: local explanations with Ollama' in the README."

function llmStatusText(s: SettingsView): string {
  const model = s.llm_model ?? 'the local model'
  if (s.llm_status === 'off') return OFF_TEXT
  if (s.llm_status === 'ready') return `Local model: ${model}, ready.`
  const detail = s.llm_detail?.trim()
  return detail
    ? `Local model: ${model}, not available: ${detail}`
    : `Local model: ${model}, not available.`
}

/** The Settings page: the display choices, the shortcuts, the daily goal and the model status. */
export function SettingsPage({
  settings,
  settingsError,
  onRetry,
  onSetting,
  onCheckLlm,
  shortcutsOn,
  onShortcutsOn,
  onShowShortcuts,
  headingRef,
}: SettingsPageProps) {
  const [checking, setChecking] = useState(false)
  const [checkFailed, setCheckFailed] = useState(false)
  const mounted = useRef(true)
  // Retry unmounts itself: focus goes to the loading status, and back to Retry if it fails again
  const loadingRef = useRef<HTMLParagraphElement>(null)
  const retryRef = useRef<HTMLButtonElement>(null)
  const retried = useRef(false)
  const pageRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!retried.current) return
    if (loadingRef.current) loadingRef.current.focus({ preventScroll: true })
    else {
      retried.current = false
      // loaded: the loading status is gone, so the heading takes focus; failed: Retry is back
      if (retryRef.current) retryRef.current.focus({ preventScroll: true })
      else pageRef.current?.querySelector('h2')?.focus({ preventScroll: true })
    }
  }, [settings, settingsError])
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const check = async () => {
    if (checking) return
    setChecking(true)
    setCheckFailed(false)
    const ok = await onCheckLlm()
    if (!mounted.current) return
    setChecking(false)
    setCheckFailed(!ok)
  }

  return (
    <div className={styles.page} data-testid="settings-page" ref={pageRef}>
      <h2 className={styles.pageTitle} ref={headingRef} tabIndex={-1}>
        Settings
      </h2>

      {settings === null ? (
        settingsError ? (
          <div className={styles.status} role="alert">
            <span>Settings couldn&apos;t be loaded.</span>
            <Button
              ref={retryRef}
              size="sm"
              onClick={() => {
                retried.current = true
                onRetry()
              }}
            >
              Retry
            </Button>
          </div>
        ) : (
          <p className={styles.status} role="status" ref={loadingRef} tabIndex={-1}>
            Loading settings…
          </p>
        )
      ) : (
        <>
          <Panel title="Table">
            <div className={styles.stack}>
              <Toggle
                label="Pot odds"
                description="Show pot odds on the table"
                on={settings.show_pot_odds}
                onChange={(on) => void onSetting({ show_pot_odds: on })}
              />
              <Toggle
                label="Show profile"
                description="Show Villain's profile on the table"
                on={settings.show_profile}
                onChange={(on) => void onSetting({ show_profile: on })}
              />
              <div className={styles.divider} />
              <Select
                label="Villain for new puzzles"
                value={settings.profile ?? ''}
                onChange={(value) => void onSetting({ profile: value === '' ? null : value })}
              >
                <option value="">Random</option>
                {settings.profiles.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.label}
                  </option>
                ))}
              </Select>
            </div>
          </Panel>

          <Panel title="Keyboard">
            <div className={styles.stack}>
              <Toggle
                label="Shortcuts"
                description="Single keys answer and move on (F, X, C, B, N and more)"
                on={shortcutsOn}
                onChange={onShortcutsOn}
              />
              <div>
                <Button size="sm" onClick={onShowShortcuts}>
                  Show all shortcuts
                </Button>
              </div>
            </div>
          </Panel>

          <Panel title="Daily goal">
            <GoalInput goal={settings.daily_goal} onGoal={(n) => onSetting({ daily_goal: n })} />
          </Panel>

          <Panel title="Explanations">
            <div className={styles.stack}>
              <p className={styles.llm} role="status">
                {checkFailed
                  ? "Couldn't check the local model. Try again."
                  : llmStatusText(settings)}
              </p>
              {settings.llm_provider !== 'none' && (
                <div>
                  <Button size="sm" busy={checking} onClick={() => void check()}>
                    {checking ? 'Checking…' : 'Check again'}
                  </Button>
                </div>
              )}
            </div>
          </Panel>
        </>
      )}
    </div>
  )
}
