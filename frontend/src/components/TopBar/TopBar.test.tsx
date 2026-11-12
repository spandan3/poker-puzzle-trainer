import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TopBar, type TopBarProps } from './TopBar'

function setup(over: Partial<TopBarProps> = {}) {
  const props: TopBarProps = {
    page: 'puzzles',
    onNavigate: vi.fn(),
    street: null,
    onStreet: vi.fn(),
    profile: null,
    profiles: [
      { name: 'tag', label: 'TAG' },
      { name: 'lag', label: 'LAG' },
    ],
    onProfile: vi.fn(),
    showPotOdds: true,
    onShowPotOdds: vi.fn(),
    showProfile: false,
    onShowProfile: vi.fn(),
    shortcutsOn: true,
    onShortcutsOn: vi.fn(),
    onHelp: vi.fn(),
    onNewPuzzle: vi.fn(),
    ...over,
  }
  render(<TopBar {...props} />)
  return { props, user: userEvent.setup() }
}

describe('TopBar', () => {
  it('shows the app title', () => {
    setup()
    expect(
      screen.getByRole('heading', { level: 1, name: 'Poker Puzzle Trainer' }),
    ).toBeInTheDocument()
  })

  it('offers the street choices and reports the selection (Any street = null)', async () => {
    const { props, user } = setup({ street: 'flop' })
    const select = screen.getByRole('combobox', { name: 'Street' })
    expect(select).toHaveValue('flop')
    expect(Array.from((select as HTMLSelectElement).options).map((o) => o.text)).toEqual([
      'Any street',
      'Pre-flop',
      'Flop',
      'Turn',
      'River',
    ])
    await user.selectOptions(select, 'river')
    expect(props.onStreet).toHaveBeenCalledWith('river')
    await user.selectOptions(select, 'Any street')
    expect(props.onStreet).toHaveBeenLastCalledWith(null)
  })

  it('offers Random plus the profiles and reports the key (Random = null)', async () => {
    const { props, user } = setup({ profile: 'tag' })
    const select = screen.getByRole('combobox', { name: 'Villain' })
    expect(select).toHaveValue('tag')
    expect(Array.from((select as HTMLSelectElement).options).map((o) => o.text)).toEqual([
      'Random',
      'TAG',
      'LAG',
    ])
    await user.selectOptions(select, 'lag')
    expect(props.onProfile).toHaveBeenCalledWith('lag')
    await user.selectOptions(select, 'Random')
    expect(props.onProfile).toHaveBeenLastCalledWith(null)
  })

  it.each([
    ['Pot odds', true, 'onShowPotOdds'],
    ['Show profile', false, 'onShowProfile'],
    ['Shortcuts', true, 'onShortcutsOn'],
  ] as const)('toggle %s flips its value', async (name, current, handler) => {
    const over = {
      'Pot odds': { showPotOdds: current },
      'Show profile': { showProfile: current },
      Shortcuts: { shortcutsOn: current },
    }[name]
    const { props, user } = setup(over)
    const toggle = screen.getByRole('switch', { name })
    expect(toggle).toHaveAttribute('aria-checked', String(current))
    await user.click(toggle)
    expect(props[handler]).toHaveBeenCalledWith(!current)
  })

  it('toggles with the keyboard', async () => {
    const { props, user } = setup({ showProfile: false })
    screen.getByRole('switch', { name: 'Show profile' }).focus()
    await user.keyboard(' ')
    expect(props.onShowProfile).toHaveBeenCalledWith(true)
  })

  it('has Help and New puzzle buttons', async () => {
    const { props, user } = setup()
    await user.click(screen.getByRole('button', { name: 'Keyboard shortcuts help' }))
    expect(props.onHelp).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: 'New puzzle' }))
    expect(props.onNewPuzzle).toHaveBeenCalledTimes(1)
  })

  describe('navigation', () => {
    it('has a Main nav of real links, the current page marked', () => {
      setup({ page: 'progress' })
      const nav = screen.getByRole('navigation', { name: 'Main' })
      const puzzles = within(nav).getByRole('link', { name: 'Puzzles' })
      const progress = within(nav).getByRole('link', { name: 'Progress' })
      expect(puzzles).toHaveAttribute('href', '/')
      expect(progress).toHaveAttribute('href', '/progress')
      expect(progress).toHaveAttribute('aria-current', 'page')
      expect(puzzles).not.toHaveAttribute('aria-current')
    })

    it('a plain left click navigates in the app', async () => {
      const { props, user } = setup()
      await user.click(screen.getByRole('link', { name: 'Progress' }))
      expect(props.onNavigate).toHaveBeenCalledWith('progress')
    })

    it('leaves modified and middle clicks to the browser', () => {
      const { props } = setup()
      const link = screen.getByRole('link', { name: 'Progress' })
      for (const init of [
        { ctrlKey: true },
        { metaKey: true },
        { shiftKey: true },
        { button: 1 },
      ]) {
        const notPrevented = fireEvent.click(link, init)
        expect(notPrevented).toBe(true)
      }
      expect(props.onNavigate).not.toHaveBeenCalled()
    })

    it('shows the puzzle controls on Puzzles only; Help stays', () => {
      const { props } = setup({ page: 'progress' })
      expect(screen.queryByRole('combobox', { name: 'Street' })).toBeNull()
      expect(screen.queryByRole('combobox', { name: 'Villain' })).toBeNull()
      expect(screen.queryByRole('switch')).toBeNull()
      expect(screen.queryByRole('button', { name: 'New puzzle' })).toBeNull()
      expect(screen.getByRole('button', { name: 'Keyboard shortcuts help' })).toBeInTheDocument()
      expect(props.onHelp).not.toHaveBeenCalled()
    })
  })
})
