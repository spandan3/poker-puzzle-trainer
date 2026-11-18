import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { PlayHandSummary } from '../../api/types'
import { playHandsFixture } from '../../test/fixture'
import type { SessionHandsApi } from './SessionHands'
import { SessionHands } from './SessionHands'

function setup(hands: PlayHandSummary[] = playHandsFixture()) {
  const api: SessionHandsApi = {
    listPlayHands: vi.fn<SessionHandsApi['listPlayHands']>(async () => hands),
  }
  const onOpen = vi.fn()
  render(<SessionHands sessionId={7} api={api} onOpen={onOpen} />)
  return { api, onOpen, user: userEvent.setup() }
}

/** the body rows of the table (the header row is not one of the hands) */
async function findRows() {
  const table = await screen.findByRole('table', { name: 'Hands' })
  return within(table).getAllByRole('row').slice(1)
}

describe('SessionHands', () => {
  it('asks for the session’s hands', async () => {
    const { api } = setup()
    await findRows()
    expect(api.listPlayHands).toHaveBeenCalledWith(7)
  })

  it('rows show the hand number, position, result and, when analysed, EV lost', async () => {
    setup()
    const rows = await findRows()
    expect(rows[0]).toHaveTextContent('Hand 1')
    expect(rows[0]).toHaveTextContent('BTN')
    expect(rows[0]).toHaveTextContent('−2.5 bb')
    expect(rows[0]).toHaveTextContent('3.17 bb')
    expect(rows[1]).toHaveTextContent('Hand 2')
    expect(rows[1]).toHaveTextContent('BB')
    expect(rows[1]).toHaveTextContent('+2.5 bb')
    expect(within(rows[1]!).getAllByRole('cell')[2]).toHaveTextContent(/^$/)
  })

  it('the button reads Review for an analysed hand and Analyse otherwise', async () => {
    setup()
    const rows = await findRows()
    expect(within(rows[0]!).getByRole('button')).toHaveTextContent('Review')
    expect(within(rows[1]!).getByRole('button')).toHaveTextContent('Analyse')
  })

  it('has no button for a hand with no decision', async () => {
    const hands = playHandsFixture()
    setup([{ ...hands[1]!, decision_count: 0, ev_loss_bb: null, analysed: false }])
    const rows = await findRows()
    expect(within(rows[0]!).queryByRole('button')).toBeNull()
  })

  it('has no button for a hand that is still running', async () => {
    const hands = playHandsFixture()
    setup([{ ...hands[1]!, ended_by: null, result_bb: null }])
    const rows = await findRows()
    expect(rows[0]).toHaveTextContent('In progress')
    expect(within(rows[0]!).queryByRole('button')).toBeNull()
  })

  it('clicking calls onOpen with the hand id', async () => {
    const { onOpen, user } = setup()
    const rows = await findRows()
    await user.click(within(rows[1]!).getByRole('button'))
    expect(onOpen).toHaveBeenCalledWith(playHandsFixture()[1]!.id)
  })

  it('says so when there are no hands', async () => {
    setup([])
    expect(await screen.findByText('No hands yet.')).toBeInTheDocument()
  })

  it('a load error shows Retry, which reloads the list', async () => {
    const listPlayHands = vi
      .fn<SessionHandsApi['listPlayHands']>()
      .mockRejectedValueOnce(new Error('down'))
      .mockResolvedValue(playHandsFixture())
    const user = userEvent.setup()
    render(<SessionHands sessionId={7} api={{ listPlayHands }} onOpen={vi.fn()} />)
    expect(await screen.findByText('Couldn’t load the hands.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect((await findRows()).length).toBe(playHandsFixture().length)
    expect(listPlayHands).toHaveBeenCalledTimes(2)
  })
})
