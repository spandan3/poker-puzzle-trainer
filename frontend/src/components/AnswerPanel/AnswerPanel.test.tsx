import { StrictMode } from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AttemptIn, PuzzleView } from '../../api/types'
import { formatDetail } from '../../lib/format'
import { SHORTCUTS } from '../../lib/shortcuts'
import { puzzleFixture } from '../../test/fixture'
import { AnswerPanel } from './AnswerPanel'

interface Props {
  view?: PuzzleView
  busy?: boolean
  error?: string | null
  customDisabledReason?: string | null
  shortcutsOn?: boolean
}

function setup(props: Props = {}) {
  const onSubmit = vi.fn<(body: AttemptIn) => void>()
  const user = userEvent.setup()
  const all = {
    view: puzzleFixture('flop_unopened'),
    busy: false,
    error: null,
    customDisabledReason: null,
    shortcutsOn: true,
    ...props,
  }
  const utils = render(
    <StrictMode>
      <AnswerPanel {...all} onSubmit={onSubmit} />
    </StrictMode>,
  )
  const rerender = (next: Props) =>
    utils.rerender(
      <StrictMode>
        <AnswerPanel {...all} {...next} onSubmit={onSubmit} />
      </StrictMode>,
    )
  return { onSubmit, user, rerender }
}

const equityBox = () => screen.getByRole('textbox', { name: /^equity/i })
const rangeBox = () => screen.getByRole('textbox', { name: /range read/i })
const customBox = () => screen.getByRole('textbox', { name: /to \(bb\)/i })
const submit = () => screen.getByRole('button', { name: /^submit/i })
const action = (name: RegExp) => screen.getByRole('button', { name })
const sizes = () => within(screen.getByRole('group', { name: /size/i })).getAllByRole('button')

describe('AnswerPanel', () => {
  it('says a replayed puzzle is practice, and says nothing for a first attempt', () => {
    const { rerender } = setup()
    expect(screen.queryByText(/Practice —/)).toBeNull()
    rerender({ view: { ...puzzleFixture('flop_unopened'), attempts_so_far: 1 } })
    expect(screen.getByText("Practice — this attempt won't count toward your stats.")).toBeVisible()
  })

  it('shows five action buttons, disabling kinds that are not offered', () => {
    setup({ view: puzzleFixture('facing_all_in') })
    expect(action(/^fold/i)).not.toHaveAttribute('aria-disabled')
    expect(action(/^check/i)).toHaveAttribute('aria-disabled', 'true')
    expect(action(/^call 42 bb/i)).not.toHaveAttribute('aria-disabled')
    expect(action(/^bet/i)).toHaveAttribute('aria-disabled', 'true')
    expect(action(/^raise/i)).toHaveAttribute('aria-disabled', 'true')
  })

  it('keeps submit disabled until equity is set and a size is chosen', async () => {
    const { user, onSubmit } = setup()
    expect(submit()).toBeDisabled()
    expect(screen.getByText(/set your equity/i)).toBeInTheDocument()
    await user.type(equityBox(), '35')
    expect(submit()).toBeDisabled()
    await user.click(action(/^bet/i))
    expect(action(/^bet/i)).toHaveAttribute('aria-pressed', 'true')
    // selecting the group selects no size
    for (const b of sizes()) expect(b).toHaveAttribute('aria-pressed', 'false')
    expect(submit()).toBeDisabled()
    expect(screen.getByText(/choose a size/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^pot · 5 bb/ }))
    expect(submit()).toBeEnabled()
    await user.click(submit())
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit).toHaveBeenCalledWith({ equity_guess: 0.35, option: 4 })
  })

  it('labels the sizes and shows the custom bounds', async () => {
    const { user } = setup()
    expect(screen.queryByRole('group', { name: /size/i })).toBeNull()
    await user.click(action(/^bet/i))
    expect(sizes().map((b) => b.getAttribute('data-size-label'))).toEqual([
      '33% · 1.5 bb',
      '50% · 2.5 bb',
      '75% · 4 bb',
      'pot · 5 bb',
      'all-in · 97.5 bb',
    ])
    expect(screen.getByText('1–97.5 bb')).toBeInTheDocument()
  })

  it('has no custom box when custom sizes are not allowed', async () => {
    const { user } = setup({ view: puzzleFixture('preflop_btn_first_in') })
    await user.click(action(/^raise/i))
    expect(sizes()).toHaveLength(3)
    expect(screen.queryByRole('textbox', { name: /to \(bb\)/i })).toBeNull()
  })

  it('submits a custom size in chips and shows inline errors for bad ones', async () => {
    const { user, onSubmit } = setup({ view: puzzleFixture('facing_postflop_raise') })
    await user.type(equityBox(), '50')
    await user.click(action(/^raise/i))
    await user.type(customBox(), '3')
    expect(customBox()).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText('Between 7.5 bb and 97.5 bb')).toBeInTheDocument()
    expect(submit()).toBeDisabled()
    await user.clear(customBox())
    await user.type(customBox(), '12.3')
    expect(screen.getByText(/steps of 0\.5/i)).toBeInTheDocument()
    await user.clear(customBox())
    await user.type(customBox(), 'abc')
    expect(screen.getByText(/enter a number/i)).toBeInTheDocument()
    await user.clear(customBox())
    await user.type(customBox(), '12.5')
    expect(customBox()).not.toHaveAttribute('aria-invalid', 'true')
    await user.click(submit())
    expect(onSubmit).toHaveBeenCalledWith({ equity_guess: 0.5, custom_to: 25 })
  })

  it('shows an inline equity error for a bad value', async () => {
    const { user } = setup()
    await user.type(equityBox(), '120')
    expect(equityBox()).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText(/whole number from 0 to 100/i)).toBeInTheDocument()
  })

  it('reflects the equity text in the slider, which starts unset', async () => {
    const { user } = setup()
    const slider = screen.getByRole('slider', { name: /equity/i })
    expect(slider).toHaveAttribute('aria-valuetext', 'not set')
    expect(slider).toHaveAttribute('data-unset', 'true')
    await user.type(equityBox(), '42')
    expect(slider).toHaveValue('42')
    expect(slider).toHaveAttribute('aria-valuetext', '42%')
    expect(slider).not.toHaveAttribute('data-unset')
  })

  it('sends the range read when set, and not when skipped', async () => {
    const { user, onSubmit } = setup()
    const skip = screen.getByRole('button', { name: /skip/i })
    expect(skip).toHaveAttribute('aria-pressed', 'true')
    await user.type(rangeBox(), '70')
    expect(skip).toHaveAttribute('aria-pressed', 'false')
    await user.type(equityBox(), '40')
    await user.click(action(/^check/i))
    await user.click(submit())
    expect(onSubmit).toHaveBeenLastCalledWith({
      equity_guess: 0.4,
      option: 0,
      range_read_guess: 0.7,
    })
    await user.click(skip)
    expect(skip).toHaveAttribute('aria-pressed', 'true')
    expect(rangeBox()).toHaveValue('')
    await user.click(submit())
    expect(onSubmit).toHaveBeenLastCalledWith({ equity_guess: 0.4, option: 0 })
  })

  it('has no range read on the river', () => {
    setup({ view: puzzleFixture('river') })
    expect(screen.queryByRole('textbox', { name: /range read/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /skip/i })).toBeNull()
  })

  it('shows intent only for a bet or raise and clears it on a passive action', async () => {
    const { user, onSubmit } = setup()
    expect(screen.queryByRole('group', { name: /intent/i })).toBeNull()
    await user.type(equityBox(), '25')
    await user.click(action(/^bet/i))
    await user.click(screen.getByRole('button', { name: /^semi-bluff/i }))
    expect(screen.getByRole('button', { name: /^semi-bluff/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await user.click(action(/^check/i))
    expect(screen.queryByRole('group', { name: /intent/i })).toBeNull()
    await user.click(action(/^bet/i))
    expect(screen.getByRole('button', { name: /^semi-bluff/i })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    await user.click(sizes()[0] as HTMLElement)
    await user.click(screen.getByRole('button', { name: /^value/i }))
    await user.click(submit())
    expect(onSubmit).toHaveBeenCalledWith({ equity_guess: 0.25, option: 1, intent: 'value' })
  })

  it('ignores clicks on disabled actions', async () => {
    const { user } = setup({ view: puzzleFixture('facing_all_in') })
    await user.click(action(/^raise/i))
    expect(action(/^raise/i)).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByRole('group', { name: /size/i })).toBeNull()
  })

  it('shows 409 and 422 errors inline and keeps the answer', async () => {
    const { user, rerender } = setup()
    await user.type(equityBox(), '40')
    await user.click(action(/^check/i))
    const validation = [
      { loc: ['body', 'equity_guess'], msg: 'bad equity', type: 'x' },
      { loc: ['body'], msg: 'give exactly one of option or custom_to', type: 'y' },
    ]
    rerender({ error: formatDetail(validation) })
    expect(screen.getByRole('alert')).toHaveTextContent(
      'bad equity; give exactly one of option or custom_to',
    )
    rerender({ error: 'Villain model changed; custom sizes are unavailable' })
    expect(screen.getByRole('alert')).toHaveTextContent('Villain model changed')
    expect(equityBox()).toHaveValue('40')
    expect(action(/^check/i)).toHaveAttribute('aria-pressed', 'true')
  })

  it('disables the custom box with the reason after a 409', async () => {
    const { user, onSubmit } = setup({
      view: puzzleFixture('custom_allowed'),
      customDisabledReason: 'Custom sizes are unavailable for this puzzle',
    })
    await user.type(equityBox(), '40')
    await user.click(action(/^bet/i))
    expect(customBox()).toBeDisabled()
    expect(customBox()).toHaveAccessibleDescription(
      expect.stringContaining('Custom sizes are unavailable for this puzzle') as string,
    )
    // 0 does nothing either
    await user.click(document.body)
    await user.keyboard('0')
    expect(customBox()).not.toHaveFocus()
    await user.click(sizes()[1] as HTMLElement)
    await user.click(submit())
    expect(onSubmit).toHaveBeenCalledWith({ equity_guess: 0.4, option: 2 })
  })

  it('resets when the puzzle changes', async () => {
    const { user, rerender } = setup()
    await user.type(equityBox(), '40')
    await user.click(action(/^check/i))
    rerender({ view: puzzleFixture('turn') })
    expect(equityBox()).toHaveValue('')
    expect(action(/^check/i)).toHaveAttribute('aria-pressed', 'false')
  })
})

describe('AnswerPanel keyboard', () => {
  it('runs a whole answer from the keyboard', async () => {
    const { user, onSubmit } = setup()
    await user.keyboard('e')
    expect(equityBox()).toHaveFocus()
    // E never types an "e" into the box it focuses
    expect(equityBox()).toHaveValue('')
    await user.keyboard('38')
    await user.keyboard('{Escape}')
    expect(equityBox()).not.toHaveFocus()
    await user.keyboard('a')
    expect(rangeBox()).toHaveFocus()
    expect(rangeBox()).toHaveValue('')
    expect(screen.getByRole('button', { name: /skip/i })).toHaveAttribute('aria-pressed', 'false')
    await user.keyboard('55{Escape}')
    await user.keyboard('b')
    expect(action(/^bet/i)).toHaveAttribute('aria-pressed', 'true')
    await user.keyboard('2')
    expect(sizes()[1]).toHaveAttribute('aria-pressed', 'true')
    await user.keyboard('L')
    expect(screen.getByRole('button', { name: /^bluff/i })).toHaveAttribute('aria-pressed', 'true')
    await user.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit).toHaveBeenCalledWith({
      equity_guess: 0.38,
      option: 2,
      range_read_guess: 0.55,
      intent: 'bluff',
    })
  })

  it('maps F, X, C, R and the size digits', async () => {
    const { user } = setup({ view: puzzleFixture('preflop_bb_facing_open') })
    await user.keyboard('f')
    expect(action(/^fold/i)).toHaveAttribute('aria-pressed', 'true')
    await user.keyboard('c')
    expect(action(/^call/i)).toHaveAttribute('aria-pressed', 'true')
    expect(action(/^fold/i)).toHaveAttribute('aria-pressed', 'false')
    // check is not offered: X does nothing
    await user.keyboard('x')
    expect(action(/^call/i)).toHaveAttribute('aria-pressed', 'true')
    await user.keyboard('3')
    expect(action(/^raise/i)).toHaveAttribute('aria-pressed', 'true')
    expect(sizes()[2]).toHaveAttribute('aria-pressed', 'true')
    // a digit past the last size does nothing
    await user.keyboard('7')
    expect(sizes()[2]).toHaveAttribute('aria-pressed', 'true')
    await user.keyboard('v')
    expect(screen.getByRole('button', { name: /^value/i })).toHaveAttribute('aria-pressed', 'true')
    await user.keyboard('s')
    expect(screen.getByRole('button', { name: /^semi-bluff/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('ignores intent keys when intent is not shown', async () => {
    const { user } = setup()
    await user.keyboard('xv')
    expect(screen.queryByRole('group', { name: /intent/i })).toBeNull()
    expect(action(/^check/i)).toHaveAttribute('aria-pressed', 'true')
  })

  it('0 focuses the custom size without typing into it', async () => {
    const { user, onSubmit } = setup()
    await user.keyboard('e40{Escape}0')
    expect(customBox()).toHaveFocus()
    expect(customBox()).toHaveValue('')
    expect(action(/^bet/i)).toHaveAttribute('aria-pressed', 'true')
    await user.keyboard('6.5{Enter}')
    expect(onSubmit).toHaveBeenCalledWith({ equity_guess: 0.4, custom_to: 13 })
  })

  it('Enter on a focused action button selects it and does not submit', async () => {
    const { user, onSubmit } = setup()
    await user.type(equityBox(), '40')
    action(/^check/i).focus()
    await user.keyboard('{Enter}')
    expect(action(/^check/i)).toHaveAttribute('aria-pressed', 'true')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('Enter in the equity box submits exactly once', async () => {
    const { user, onSubmit } = setup()
    await user.click(action(/^check/i))
    await user.type(equityBox(), '40{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit).toHaveBeenCalledWith({ equity_guess: 0.4, option: 0 })
  })

  it('Enter in the equity box does nothing while the answer is incomplete', async () => {
    const { user, onSubmit } = setup()
    await user.type(equityBox(), '40{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('a second Enter while busy sends nothing', async () => {
    const { user, onSubmit, rerender } = setup()
    await user.click(action(/^check/i))
    await user.type(equityBox(), '40{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
    rerender({ busy: true })
    expect(submit()).toBeDisabled()
    await user.keyboard('{Enter}')
    await user.keyboard('{Escape}{Enter}')
    await user.click(submit())
    expect(onSubmit).toHaveBeenCalledTimes(1)
    // shortcuts don't change the answer while busy
    await user.keyboard('f')
    expect(action(/^check/i)).toHaveAttribute('aria-pressed', 'true')
    rerender({ busy: false })
    await user.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(2)
  })

  it('sends one request for two Enters before busy changes', async () => {
    const { user, onSubmit } = setup()
    await user.click(action(/^check/i))
    await user.type(equityBox(), '40')
    await user.keyboard('{Enter}{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
    // and from the body, through the global Enter
    await user.keyboard('{Escape}{Enter}{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('sends one request for two submit clicks before busy changes', async () => {
    const { user, onSubmit } = setup()
    await user.click(action(/^check/i))
    await user.type(equityBox(), '40')
    await user.click(submit())
    await user.click(submit())
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('ignores clicks and typing while busy', async () => {
    const { user, rerender } = setup()
    await user.click(action(/^check/i))
    await user.type(equityBox(), '40')
    rerender({ busy: true })
    await user.click(action(/^fold/i))
    await user.type(equityBox(), '5')
    expect(action(/^check/i)).toHaveAttribute('aria-pressed', 'true')
    expect(action(/^fold/i)).toHaveAttribute('aria-pressed', 'false')
    expect(equityBox()).toHaveValue('40')
  })

  it('Enter on the focused equity slider submits', async () => {
    const { user, onSubmit } = setup()
    await user.click(action(/^check/i))
    await user.type(equityBox(), '40')
    screen.getByRole('slider', { name: /equity/i }).focus()
    await user.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('announces the submit reason and field errors politely', async () => {
    const { user } = setup()
    expect(screen.getByText(/set your equity/i)).toHaveAttribute('aria-live', 'polite')
    await user.type(equityBox(), '120')
    expect(screen.getByText(/whole number from 0 to 100/i)).toHaveAttribute('aria-live', 'polite')
    // the help text stays in the description alongside the error
    const describedBy = equityBox().getAttribute('aria-describedby')?.split(' ') ?? []
    expect(describedBy).toHaveLength(2)
    expect(equityBox()).toHaveAccessibleDescription(/vs villain's range.*whole number/i)
  })

  it('ignores a key pressed inside a select', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(
      <>
        <select aria-label="Street">
          <option>Flop</option>
          <option>Turn</option>
        </select>
        <AnswerPanel
          view={puzzleFixture('facing_all_in')}
          onSubmit={onSubmit}
          busy={false}
          error={null}
          customDisabledReason={null}
          shortcutsOn
        />
      </>,
    )
    screen.getByRole('combobox', { name: 'Street' }).focus()
    await user.keyboard('fc')
    expect(action(/^fold/i)).toHaveAttribute('aria-pressed', 'false')
    expect(action(/^call/i)).toHaveAttribute('aria-pressed', 'false')
  })

  it('does nothing and shows no hints when shortcuts are off', async () => {
    const { user } = setup({ shortcutsOn: false })
    await user.keyboard('xe')
    expect(action(/^check/i)).toHaveAttribute('aria-pressed', 'false')
    expect(equityBox()).not.toHaveFocus()
    expect(document.querySelectorAll('kbd')).toHaveLength(0)
    expect(document.querySelectorAll('[aria-keyshortcuts]')).toHaveLength(0)
  })

  it('every panel shortcut has a <kbd> hint and aria-keyshortcuts', async () => {
    const { user } = setup({ view: puzzleFixture('custom_allowed') })
    await user.click(action(/^bet/i))
    const panelShortcuts = SHORTCUTS.filter((s) => s.scope === 'panel')
    expect(panelShortcuts.map((s) => s.id)).toEqual(
      expect.arrayContaining(['fold', 'check', 'call', 'aggressive', 'size', 'customSize']),
    )
    for (const s of panelShortcuts) {
      const nodes = document.querySelectorAll(`[data-shortcut="${s.id}"]`)
      expect(nodes.length, s.id).toBeGreaterThan(0)
      const allowed = new Set(s.aria.split(' '))
      for (const node of nodes) {
        const aria = node.getAttribute('aria-keyshortcuts') ?? ''
        expect(aria, s.id).not.toBe('')
        for (const k of aria.split(' ')) expect(allowed.has(k), `${s.id} ${k}`).toBe(true)
        const hint =
          node.querySelector('kbd') ?? node.closest('[data-shortcut-scope]')?.querySelector('kbd')
        expect(hint, s.id).not.toBeNull()
        expect(s.keys, s.id).toContain(hint?.textContent)
      }
    }
    // the size buttons are numbered 1..n
    expect(sizes().map((b) => b.querySelector('kbd')?.textContent)).toEqual([
      '1',
      '2',
      '3',
      '4',
      '5',
    ])
    expect(sizes().map((b) => b.getAttribute('aria-keyshortcuts'))).toEqual([
      '1',
      '2',
      '3',
      '4',
      '5',
    ])
  })
})
