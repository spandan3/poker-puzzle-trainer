import { renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { KeyEventLike, ShortcutId } from './shortcuts'
import { SHORTCUTS, keyToCommand, useShortcuts } from './shortcuts'

const ON = { enabled: true }

function el(html: string): Element {
  const host = document.createElement('div')
  host.innerHTML = html
  document.body.append(host)
  return host.firstElementChild as Element
}

afterEach(() => {
  document.body.innerHTML = ''
})

function key(k: string, extra: Partial<KeyEventLike> = {}): KeyEventLike {
  return { key: k, target: document.body, ...extra }
}

describe('keyToCommand', () => {
  const table: [string, ShortcutId, number?][] = [
    ['f', 'fold'],
    ['x', 'check'],
    ['c', 'call'],
    ['b', 'aggressive'],
    ['r', 'aggressive'],
    ['1', 'size', 1],
    ['5', 'size', 5],
    ['9', 'size', 9],
    ['0', 'customSize'],
    ['v', 'value'],
    ['l', 'bluff'],
    ['s', 'semiBluff'],
    ['e', 'focusEquity'],
    ['a', 'focusRangeRead'],
    ['Enter', 'submit'],
    ['Escape', 'escape'],
    ['n', 'next'],
    ['?', 'help'],
    ['h', 'help'],
  ]

  it.each(table)('maps %s to %s', (k, id, n) => {
    expect(keyToCommand(key(k), ON)).toEqual(n === undefined ? { id } : { id, n })
  })

  it('matches letters case-insensitively and allows Shift', () => {
    expect(keyToCommand(key('F', { shiftKey: true }), ON)).toEqual({ id: 'fold' })
    expect(keyToCommand(key('B'), ON)).toEqual({ id: 'aggressive' })
    expect(keyToCommand(key('/', { shiftKey: true }), ON)).toEqual({ id: 'help' })
    expect(keyToCommand(key('/'), ON)).toBeNull()
  })

  it('never fires with Ctrl, Alt or Meta', () => {
    for (const mod of ['ctrlKey', 'altKey', 'metaKey'] as const) {
      expect(keyToCommand(key('f', { [mod]: true }), ON)).toBeNull()
      expect(keyToCommand(key('Enter', { [mod]: true }), ON)).toBeNull()
    }
  })

  it('ignores unknown keys', () => {
    for (const k of ['q', 'z', 'ArrowUp', 'Tab', ' ', 'Shift', '-']) {
      expect(keyToCommand(key(k), ON)).toBeNull()
    }
  })

  it('is off when disabled', () => {
    for (const [k] of table) expect(keyToCommand(key(k), { enabled: false })).toBeNull()
  })

  it('ignores keys while typing in text inputs, textareas, selects and contenteditable', () => {
    const targets = [
      el('<input type="text">'),
      el('<input>'),
      el('<input type="number">'),
      el('<input type="search">'),
      el('<textarea></textarea>'),
      el('<select><option>a</option></select>'),
      el('<div contenteditable="true">x</div>'),
    ]
    for (const target of targets) {
      for (const k of ['f', 'e', '1', '0', 'Enter', '?', 'n']) {
        expect(keyToCommand(key(k, { target }), ON), `${target.outerHTML} ${k}`).toBeNull()
      }
      // Escape still works, to leave the field
      expect(keyToCommand(key('Escape', { target }), ON)).toEqual({ id: 'escape' })
    }
  })

  it('stays active on range inputs, buttons and checkboxes', () => {
    for (const html of ['<input type="range">', '<button>b</button>', '<input type="checkbox">']) {
      expect(keyToCommand(key('f', { target: el(html) }), ON)).toEqual({ id: 'fold' })
      expect(keyToCommand(key('2', { target: el(html) }), ON)).toEqual({ id: 'size', n: 2 })
    }
  })

  it('submits on Enter only from the body, a non-form element or a range slider', () => {
    expect(keyToCommand(key('Enter', { target: el('<div tabindex="0"></div>') }), ON)).toEqual({
      id: 'submit',
    })
    expect(keyToCommand(key('Enter', { target: el('<input type="range">') }), ON)).toEqual({
      id: 'submit',
    })
    for (const html of ['<button>b</button>', '<input type="checkbox">']) {
      expect(keyToCommand(key('Enter', { target: el(html) }), ON)).toBeNull()
    }
    expect(keyToCommand(key('Enter', { target: el('<a href="#x">x</a>') }), ON)).toBeNull()
  })
})

describe('SHORTCUTS', () => {
  it('has one entry per command, each with keys, aria-keyshortcuts and a description', () => {
    const ids = SHORTCUTS.map((s) => s.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const s of SHORTCUTS) {
      expect(s.keys.length).toBeGreaterThan(0)
      expect(s.aria.length).toBeGreaterThan(0)
      expect(s.description.length).toBeGreaterThan(0)
    }
  })

  it('agrees with keyToCommand for every listed key', () => {
    for (const s of SHORTCUTS) {
      for (const k of s.aria.split(' ')) {
        const parts = k.split('+')
        const base = parts[parts.length - 1] as string
        const shiftKey = parts.includes('Shift')
        const cmd = keyToCommand(
          key(base.length === 1 ? base.toLowerCase() : base, { shiftKey }),
          ON,
        )
        expect(cmd?.id, `${s.id} ${k}`).toBe(s.id)
      }
    }
  })
})

describe('useShortcuts', () => {
  it('dispatches commands and prevents the default for handled keys', () => {
    const handler = vi.fn((cmd: { id: string }) => cmd.id !== 'next')
    renderHook(() => useShortcuts(handler, true))

    const f = new KeyboardEvent('keydown', { key: 'f', bubbles: true, cancelable: true })
    document.body.dispatchEvent(f)
    expect(handler).toHaveBeenCalledWith({ id: 'fold' }, f)
    expect(f.defaultPrevented).toBe(true)

    // a command the handler declines is left alone
    const n = new KeyboardEvent('keydown', { key: 'n', bubbles: true, cancelable: true })
    document.body.dispatchEvent(n)
    expect(n.defaultPrevented).toBe(false)

    // an unmapped key never reaches the handler
    const q = new KeyboardEvent('keydown', { key: 'q', bubbles: true, cancelable: true })
    document.body.dispatchEvent(q)
    expect(handler).toHaveBeenCalledTimes(2)
    expect(q.defaultPrevented).toBe(false)
  })

  it('does nothing when off', () => {
    const handler = vi.fn(() => true)
    renderHook(() => useShortcuts(handler, false))
    const f = new KeyboardEvent('keydown', { key: 'f', bubbles: true, cancelable: true })
    document.body.dispatchEvent(f)
    expect(handler).not.toHaveBeenCalled()
    expect(f.defaultPrevented).toBe(false)
  })

  it('ignores keys typed in a select', () => {
    const handler = vi.fn(() => true)
    renderHook(() => useShortcuts(handler, true))
    const select = el('<select><option>a</option></select>')
    const f = new KeyboardEvent('keydown', { key: 'f', bubbles: true, cancelable: true })
    select.dispatchEvent(f)
    expect(handler).not.toHaveBeenCalled()
    expect(f.defaultPrevented).toBe(false)
  })
})
