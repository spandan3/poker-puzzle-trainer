import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SHORTCUTS } from '../../lib/shortcuts'
import { puzzleFixture } from '../../test/fixture'
import { AnswerPanel } from '../AnswerPanel/AnswerPanel'
import { ShortcutsOverlay } from './ShortcutsOverlay'

describe('ShortcutsOverlay', () => {
  it('renders nothing when closed', () => {
    render(<ShortcutsOverlay open={false} onClose={() => {}} />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('lists every shortcut with its keys', () => {
    render(<ShortcutsOverlay open onClose={() => {}} />)
    const dialog = screen.getByRole('dialog', { name: 'Keyboard shortcuts' })
    for (const s of SHORTCUTS) {
      const row = dialog.querySelector(`[data-shortcut-row="${s.id}"]`) as HTMLElement
      expect(row, s.id).not.toBeNull()
      expect(within(row).getByText(s.description)).toBeInTheDocument()
      const kbds = [...row.querySelectorAll('kbd')].map((k) => k.textContent)
      expect(kbds).toEqual(s.keysLabel ? [s.keysLabel] : s.keys)
    }
  })

  it('keeps shortcuts from reaching the page behind it', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const pageKeys = vi.fn()
    window.addEventListener('keydown', pageKeys)
    render(
      <>
        <AnswerPanel
          view={puzzleFixture('facing_all_in')}
          onSubmit={() => {}}
          busy={false}
          error={null}
          customDisabledReason={null}
          shortcutsOn
        />
        <ShortcutsOverlay open onClose={onClose} />
      </>,
    )
    await user.keyboard('fce')
    expect(screen.getByRole('button', { name: /^fold/i })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: /^call/i })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('textbox', { name: /^equity/i })).not.toHaveFocus()
    expect(pageKeys).not.toHaveBeenCalled()
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(pageKeys).not.toHaveBeenCalled()
    window.removeEventListener('keydown', pageKeys)
  })

  it('focuses Close, closes on Escape and on the button, and restores focus', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const { rerender } = render(
      <>
        <button type="button">Help</button>
        <ShortcutsOverlay open={false} onClose={onClose} />
      </>,
    )
    const help = screen.getByRole('button', { name: 'Help' })
    help.focus()
    rerender(
      <>
        <button type="button">Help</button>
        <ShortcutsOverlay open onClose={onClose} />
      </>,
    )
    expect(screen.getByRole('button', { name: /close/i })).toHaveFocus()
    await user.keyboard('{Tab}')
    expect(screen.getByRole('button', { name: /close/i })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalledTimes(2)
    rerender(
      <>
        <button type="button">Help</button>
        <ShortcutsOverlay open={false} onClose={onClose} />
      </>,
    )
    expect(help).toHaveFocus()
  })
})
