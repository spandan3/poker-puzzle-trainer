import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Badge, Button, ConfirmDialog, Panel, Select, Toggle } from '.'

describe('Button', () => {
  it('shows its variant and size as data attributes', () => {
    render(
      <Button variant="primary" size="sm">
        Go
      </Button>,
    )
    const b = screen.getByRole('button', { name: 'Go' })
    expect(b).toHaveAttribute('data-variant', 'primary')
    expect(b).toHaveAttribute('data-size', 'sm')
  })

  it('busy is aria-disabled, keeps focus and ignores clicks', async () => {
    const onClick = vi.fn()
    render(
      <Button busy onClick={onClick}>
        Check
      </Button>,
    )
    const b = screen.getByRole('button', { name: 'Check' })
    b.focus()
    await userEvent.click(b)
    expect(b).toHaveAttribute('aria-disabled', 'true')
    expect(b).not.toBeDisabled()
    expect(b).toHaveFocus()
    expect(onClick).not.toHaveBeenCalled()
  })

  it('disabled is native', () => {
    render(<Button disabled>Prev</Button>)
    expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled()
  })

  it('calls onClick, and hides the key hint from assistive tech', async () => {
    const onClick = vi.fn()
    render(
      <Button kbd="N" onClick={onClick}>
        New
      </Button>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'New' }))
    expect(onClick).toHaveBeenCalledOnce()
    expect(screen.getByText('N')).toHaveAttribute('aria-hidden', 'true')
  })
})

describe('Select', () => {
  it('is named by its label and reports the value', async () => {
    const onChange = vi.fn()
    render(
      <Select label="Street" value="" onChange={onChange}>
        <option value="">Any street</option>
        <option value="river">River</option>
      </Select>,
    )
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Street' }), 'river')
    expect(onChange).toHaveBeenCalledWith('river')
  })
})

describe('Badge', () => {
  it('shows its tone as a data attribute', () => {
    render(<Badge tone="blunder">Blunder</Badge>)
    expect(screen.getByText('Blunder')).toHaveAttribute('data-tone', 'blunder')
  })
})

describe('Panel', () => {
  it('renders the title at the requested level', () => {
    render(
      <Panel title="Table" headingLevel={2}>
        body
      </Panel>,
    )
    expect(screen.getByRole('heading', { level: 2, name: 'Table' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Table' })).toBeInTheDocument()
  })

  it('flush marks the panel for no padding', () => {
    render(
      <Panel title="Rows" flush>
        x
      </Panel>,
    )
    expect(screen.getByRole('region', { name: 'Rows' })).toHaveAttribute('data-flush')
  })
})

describe('Toggle', () => {
  function Harness() {
    const [on, setOn] = useState(false)
    return <Toggle label="Pot odds" on={on} onChange={setOn} />
  }

  it('is a switch that flips on click and on Space', async () => {
    render(<Harness />)
    const sw = screen.getByRole('switch', { name: 'Pot odds' })
    expect(sw).toHaveAttribute('aria-checked', 'false')
    await userEvent.click(sw)
    expect(sw).toHaveAttribute('aria-checked', 'true')
    sw.focus()
    await userEvent.keyboard(' ')
    expect(sw).toHaveAttribute('aria-checked', 'false')
  })

  it('links its description', () => {
    render(<Toggle label="A" on={false} onChange={() => {}} description="More about A" />)
    expect(screen.getByRole('switch')).toHaveAccessibleDescription('More about A')
  })
})

describe('ConfirmDialog', () => {
  function Harness(props: { onConfirm?: () => void; onCancel?: () => void }) {
    const [open, setOpen] = useState(false)
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Open
        </button>
        {open && (
          <ConfirmDialog
            title="Leave puzzle?"
            body="Your answer is not saved."
            confirmLabel="Leave"
            cancelLabel="Stay"
            onConfirm={() => {
              props.onConfirm?.()
              setOpen(false)
            }}
            onCancel={() => {
              props.onCancel?.()
              setOpen(false)
            }}
          />
        )}
      </>
    )
  }

  it('focuses the cancel button on open', async () => {
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: 'Open' }))
    expect(screen.getByRole('button', { name: 'Stay' })).toHaveFocus()
  })

  it('Escape cancels and no window bubble listener sees it', async () => {
    const onCancel = vi.fn()
    const seen = vi.fn()
    window.addEventListener('keydown', seen)
    render(<Harness onCancel={onCancel} />)
    await userEvent.click(screen.getByRole('button', { name: 'Open' }))
    await userEvent.keyboard('{Escape}')
    window.removeEventListener('keydown', seen)
    expect(onCancel).toHaveBeenCalledOnce()
    expect(seen).not.toHaveBeenCalled()
  })

  it('shortcut keys do not reach the page', async () => {
    const seen = vi.fn()
    window.addEventListener('keydown', seen)
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: 'Open' }))
    await userEvent.keyboard('n?')
    window.removeEventListener('keydown', seen)
    expect(seen).not.toHaveBeenCalled()
  })

  it('confirm calls onConfirm', async () => {
    const onConfirm = vi.fn()
    render(<Harness onConfirm={onConfirm} />)
    await userEvent.click(screen.getByRole('button', { name: 'Open' }))
    await userEvent.click(screen.getByRole('button', { name: 'Leave' }))
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('returns focus to the opener on close', async () => {
    render(<Harness />)
    const opener = screen.getByRole('button', { name: 'Open' })
    await userEvent.click(opener)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('button', { name: 'Stay' })).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })
})
