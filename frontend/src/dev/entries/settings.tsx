import { useState } from 'react'
import type { CSSProperties } from 'react'
import type { SettingsPatch, SettingsView } from '../../api/types'
import { SettingsPage } from '../../components/Settings/SettingsPage'
import { settingsFixture } from '../../test/fixture'
import type { GalleryEntry } from '../Gallery'

const caption: CSSProperties = {
  margin: 'var(--space-5) 0 var(--space-2)',
  color: 'var(--color-text-muted)',
  fontSize: 'var(--text-sm)',
}

const ollama = (over: Partial<SettingsView>): SettingsView => ({
  ...settingsFixture(),
  llm_provider: 'ollama',
  llm_model: 'llama3.2:3b',
  ...over,
})

/** The page with local state, so the switches, the select and "Check again" work in the gallery. */
function Live({ initial }: { initial: SettingsView | null }) {
  const [settings, setSettings] = useState(initial)
  const [shortcutsOn, setShortcutsOn] = useState(true)
  const [error, setError] = useState(false)
  return (
    <SettingsPage
      settings={settings}
      settingsError={error}
      onRetry={() => setError(false)}
      onSetting={async (patch: SettingsPatch) => {
        setSettings((s) => (s ? { ...s, ...patch } : s))
        return true
      }}
      onCheckLlm={async () => {
        await new Promise((resolve) => setTimeout(resolve, 800))
        setSettings((s) => (s ? { ...s, llm_status: 'ready', llm_detail: null } : s))
        return true
      }}
      shortcutsOn={shortcutsOn}
      onShortcutsOn={setShortcutsOn}
      onShowShortcuts={() => {}}
    />
  )
}

const entry: GalleryEntry = {
  title: 'Settings',
  render: () => (
    <div>
      <p style={caption}>Provider off (the default)</p>
      <Live initial={settingsFixture()} />

      <p style={caption}>Local model ready</p>
      <Live initial={ollama({ llm_status: 'ready', llm_detail: null })} />

      <p style={caption}>Local model unavailable (Check again turns it ready)</p>
      <Live
        initial={ollama({
          llm_status: 'unavailable',
          llm_detail: 'Ollama isn’t answering at http://127.0.0.1:11434.',
        })}
      />

      <p style={caption}>Loading</p>
      <SettingsPage
        settings={null}
        settingsError={false}
        onRetry={() => {}}
        onSetting={async () => true}
        onCheckLlm={async () => true}
        shortcutsOn
        onShortcutsOn={() => {}}
        onShowShortcuts={() => {}}
      />

      <p style={caption}>Failed to load</p>
      <SettingsPage
        settings={null}
        settingsError
        onRetry={() => {}}
        onSetting={async () => true}
        onCheckLlm={async () => true}
        shortcutsOn
        onShortcutsOn={() => {}}
        onShowShortcuts={() => {}}
      />
    </div>
  ),
}

export default entry
