import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { SettingsView } from '../../api/types'
import { settingsFixture } from '../../test/fixture'
import type { SettingsPageProps } from './SettingsPage'
import { SettingsPage } from './SettingsPage'

const ollama = (over: Partial<SettingsView> = {}): SettingsView => ({
  ...settingsFixture(),
  llm_provider: 'ollama',
  llm_model: 'llama3.2:3b',
  llm_status: 'ready',
  llm_detail: null,
  ...over,
})

function setup(over: Partial<SettingsPageProps> = {}) {
  const props: SettingsPageProps = {
    settings: settingsFixture(),
    settingsError: false,
    onRetry: vi.fn(),
    onSetting: vi.fn(async () => true),
    onCheckLlm: vi.fn(async () => true),
    shortcutsOn: true,
    onShortcutsOn: vi.fn(),
    onShowShortcuts: vi.fn(),
    ...over,
  }
  const user = userEvent.setup()
  const view = render(<SettingsPage {...props} />)
  return { user, props, ...view }
}

const goal = () => screen.getByRole('spinbutton', { name: 'Puzzles per day' })

describe('SettingsPage', () => {
  it('has the page heading and the four sections', () => {
    setup()
    expect(screen.getByRole('heading', { level: 2, name: 'Settings' })).toBeVisible()
    const sections = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(sections).toEqual(['Table', 'Keyboard', 'Daily goal', 'Explanations'])
  })

  it('the toggles and the Villain select send the right patch', async () => {
    const { user, props } = setup()
    await user.click(screen.getByRole('switch', { name: /Pot odds/ }))
    expect(props.onSetting).toHaveBeenLastCalledWith({ show_pot_odds: false })
    await user.click(screen.getByRole('switch', { name: /Show profile/ }))
    expect(props.onSetting).toHaveBeenLastCalledWith({ show_profile: false })
    await user.selectOptions(screen.getByLabelText('Villain for new puzzles'), 'lag')
    expect(props.onSetting).toHaveBeenLastCalledWith({ profile: 'lag' })
  })

  it('Random sends a null profile, and the select shows the current one', async () => {
    const { user, props } = setup({ settings: { ...settingsFixture(), profile: 'tag' } })
    const select = screen.getByLabelText('Villain for new puzzles')
    expect(select).toHaveValue('tag')
    await user.selectOptions(select, 'Random')
    expect(props.onSetting).toHaveBeenLastCalledWith({ profile: null })
  })

  it('shows the switches as they are set', () => {
    setup({
      settings: { ...settingsFixture(), show_pot_odds: false },
      shortcutsOn: false,
    })
    expect(screen.getByRole('switch', { name: /Pot odds/ })).toHaveAttribute(
      'aria-checked',
      'false',
    )
    expect(screen.getByRole('switch', { name: /Show profile/ })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    expect(screen.getByRole('switch', { name: /Shortcuts/ })).toHaveAttribute(
      'aria-checked',
      'false',
    )
  })

  it('the Shortcuts switch and the overlay button call their handlers', async () => {
    const { user, props } = setup()
    await user.click(screen.getByRole('switch', { name: /Shortcuts/ }))
    expect(props.onShortcutsOn).toHaveBeenCalledWith(false)
    await user.click(screen.getByRole('button', { name: 'Show all shortcuts' }))
    expect(props.onShowShortcuts).toHaveBeenCalledTimes(1)
  })

  describe('daily goal', () => {
    it('commits on Enter and on blur', async () => {
      const { user, props } = setup()
      await user.clear(goal())
      await user.type(goal(), '12{Enter}')
      expect(props.onSetting).toHaveBeenLastCalledWith({ daily_goal: 12 })
      await user.clear(goal())
      await user.type(goal(), '15')
      await user.tab()
      expect(props.onSetting).toHaveBeenLastCalledWith({ daily_goal: 15 })
    })

    it.each(['0', '501'])('refuses %s', async (text) => {
      const { user, props } = setup()
      await user.clear(goal())
      await user.type(goal(), `${text}{Enter}`)
      expect(props.onSetting).not.toHaveBeenCalled()
      expect(screen.getByRole('alert')).toHaveTextContent('Enter a whole number from 1 to 500')
    })
  })

  describe('explanations', () => {
    const status = () => screen.getByRole('status')

    it('off: says the templates are used and has no Check again', () => {
      setup()
      expect(status()).toHaveTextContent(
        "Explanations come from the trainer's templates. A local model (Ollama) can reword them; see 'Optional: local explanations with Ollama' in the README.",
      )
      expect(screen.queryByRole('button', { name: /Check again/ })).toBeNull()
    })

    it('ready: names the model', () => {
      setup({ settings: ollama() })
      expect(status()).toHaveTextContent('Local model: llama3.2:3b, ready.')
      expect(screen.getByRole('button', { name: 'Check again' })).toBeVisible()
    })

    it('unavailable: gives the detail', () => {
      setup({
        settings: ollama({ llm_status: 'unavailable', llm_detail: 'Ollama is not running.' }),
      })
      expect(status()).toHaveTextContent(
        'Local model: llama3.2:3b, not available: Ollama is not running.',
      )
    })

    it('the status line is a live region and has no .env or path text', () => {
      setup({ settings: ollama() })
      expect(status()).toBeInTheDocument()
      const panel = screen.getByRole('region', { name: 'Explanations' })
      expect(panel.textContent).not.toMatch(/\.env|backend\//)
    })

    it('Check again calls onCheckLlm, reads Checking… and is aria-disabled until it resolves', async () => {
      let finish!: (ok: boolean) => void
      const onCheckLlm = vi.fn(() => new Promise<boolean>((resolve) => (finish = resolve)))
      const { user } = setup({ settings: ollama(), onCheckLlm })
      await user.click(screen.getByRole('button', { name: 'Check again' }))
      expect(onCheckLlm).toHaveBeenCalledTimes(1)
      const busy = screen.getByRole('button', { name: 'Checking…' })
      expect(busy).toHaveAttribute('aria-disabled', 'true')
      await user.click(busy)
      expect(onCheckLlm).toHaveBeenCalledTimes(1)
      finish(true)
      const again = await screen.findByRole('button', { name: 'Check again' })
      expect(again).not.toHaveAttribute('aria-disabled')
    })

    it('a failed check says so in the status line', async () => {
      const { user } = setup({ settings: ollama(), onCheckLlm: vi.fn(async () => false) })
      await user.click(screen.getByRole('button', { name: 'Check again' }))
      await waitFor(() => expect(status()).toHaveTextContent("Couldn't check the local model"))
    })
  })

  describe('loading and failed states', () => {
    it('settings === null shows Loading settings…', () => {
      setup({ settings: null })
      expect(screen.getByRole('status')).toHaveTextContent('Loading settings…')
      expect(screen.queryByRole('switch')).toBeNull()
    })

    it('a failed load shows the failure and Retry', async () => {
      const { user, props } = setup({ settings: null, settingsError: true })
      const alert = screen.getByRole('alert')
      expect(alert).toHaveTextContent("Settings couldn't be loaded.")
      await user.click(within(alert).getByRole('button', { name: 'Retry' }))
      expect(props.onRetry).toHaveBeenCalledTimes(1)
    })

    it('Retry moves focus to the loading status, and back to Retry if it fails again', async () => {
      const { user, props, rerender } = setup({ settings: null, settingsError: true })
      await user.click(screen.getByRole('button', { name: 'Retry' }))
      // the parent clears the error: the button is replaced by the loading status
      rerender(<SettingsPage {...props} settings={null} settingsError={false} />)
      expect(screen.getByRole('status')).toHaveFocus()
      rerender(<SettingsPage {...props} settings={null} settingsError={true} />)
      expect(screen.getByRole('button', { name: 'Retry' })).toHaveFocus()
    })

    it('a Retry that loads moves focus from the loading status to the page heading', async () => {
      const { user, props, rerender } = setup({ settings: null, settingsError: true })
      await user.click(screen.getByRole('button', { name: 'Retry' }))
      rerender(<SettingsPage {...props} settings={null} settingsError={false} />)
      expect(screen.getByRole('status')).toHaveFocus()
      rerender(<SettingsPage {...props} settings={settingsFixture()} settingsError={false} />)
      expect(screen.getByRole('heading', { level: 2, name: 'Settings' })).toHaveFocus()
    })
  })
})
