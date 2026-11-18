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
    shortcutsOn: true,
    onHelp: vi.fn(),
    onNewPuzzle: vi.fn(),
    tally: null,
    onEndSession: vi.fn(),
    ...over,
  }
  render(<TopBar {...props} />)
  return { props, user: userEvent.setup() }
}

describe('TopBar', () => {
  it('has a Settings link (the gear) outside the nav, current on /settings, with no page controls there', async () => {
    const { props, user } = setup()
    const gear = screen.getByRole('link', { name: 'Settings' })
    expect(gear).toHaveAttribute('href', '/settings')
    expect(gear).not.toHaveAttribute('aria-current')
    expect(
      within(screen.getByRole('navigation', { name: 'Main' })).queryByText('Settings'),
    ).toBeNull()
    await user.click(gear)
    expect(props.onNavigate).toHaveBeenCalledWith('settings')
  })

  it('on Settings the gear is current and the puzzle controls are gone', () => {
    setup({ page: 'settings' })
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByRole('combobox', { name: 'Street' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'New puzzle' })).toBeNull()
  })

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

  it.each(['puzzles', 'play', 'progress', 'settings'] as const)(
    'on %s: the nav and the Settings link are there, the Settings link is the last control, and there is no switch',
    (page) => {
      setup({ page, tally: '0 bb · 0 hands' })
      const nav = screen.getByRole('navigation', { name: 'Main' })
      expect(within(nav).getAllByRole('link')).toHaveLength(3)
      const header = screen.getByRole('banner')
      const controls = Array.from(header.querySelectorAll('a[href], button, select, input'))
      expect(controls.at(-1)).toBe(screen.getByRole('link', { name: 'Settings' }))
      expect(screen.queryByRole('switch')).toBeNull()
    },
  )

  it('Puzzles shows Street and Villain (selects), help and New puzzle', () => {
    setup({ page: 'puzzles' })
    expect(screen.getByRole('combobox', { name: 'Street' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Villain' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Keyboard shortcuts help' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New puzzle' })).toBeInTheDocument()
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

    it('shows the puzzle controls and Help on Puzzles only', () => {
      setup({ page: 'progress' })
      expect(screen.queryByRole('combobox', { name: 'Street' })).toBeNull()
      expect(screen.queryByRole('combobox', { name: 'Villain' })).toBeNull()
      expect(screen.queryByRole('button', { name: 'New puzzle' })).toBeNull()
      // shortcuts are off on Progress: no help button either
      expect(screen.queryByRole('button', { name: 'Keyboard shortcuts help' })).toBeNull()
    })
  })

  describe('Play', () => {
    it('has a Play link between Puzzles and Progress', () => {
      setup({ page: 'play' })
      const nav = screen.getByRole('navigation', { name: 'Main' })
      const links = within(nav).getAllByRole('link')
      expect(links.map((l) => l.textContent)).toEqual(['Puzzles', 'Play', 'Progress'])
      expect(links[1]).toHaveAttribute('href', '/play')
      expect(links[1]).toHaveAttribute('aria-current', 'page')
    })

    it('shows the tally and End session instead of the puzzle controls', async () => {
      const { props, user } = setup({ page: 'play', tally: '+12.5 bb · 14 hands' })
      expect(screen.getByText('+12.5 bb · 14 hands')).toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: 'End session' }))
      expect(props.onEndSession).toHaveBeenCalledTimes(1)
      expect(screen.queryByRole('combobox', { name: 'Street' })).toBeNull()
      expect(screen.queryByRole('combobox', { name: 'Villain' })).toBeNull()
      expect(screen.queryByRole('button', { name: /New puzzle/ })).toBeNull()
    })

    it('keeps help, and the tally uses tabular numbers in the sans font, not the monospace one', () => {
      setup({ page: 'play', tally: '0 bb · 0 hands' })
      expect(screen.getByRole('button', { name: 'Keyboard shortcuts help' })).toBeInTheDocument()
      const tally = screen.getByLabelText('Session tally')
      expect(tally.className).toMatch(/tabularNums/)
      expect(tally.className).not.toMatch(/mono/i)
    })

    it('has no tally or End session without a session', () => {
      setup({ page: 'play', tally: null })
      expect(screen.queryByRole('button', { name: 'End session' })).toBeNull()
    })
  })
})
