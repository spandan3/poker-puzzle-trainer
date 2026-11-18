import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import entry from './entries/play'

describe('the Play gallery entries', () => {
  it('render no main element of their own (the gallery has one)', () => {
    render(<main>{entry.render()}</main>)
    expect(screen.getAllByRole('main')).toHaveLength(1)
  })
})
