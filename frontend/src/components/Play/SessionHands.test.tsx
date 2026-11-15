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

describe('SessionHands', () => {
  it('asks for the session’s hands', async () => {
    const { api } = setup()
    await screen.findAllByRole('listitem')
    expect(api.listPlayHands).toHaveBeenCalledWith(7)
  })

  it('rows show the hand number, position, result and, when analysed, EV lost', async () => {
    setup()
    const rows = await screen.findAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('Hand 1')
    expect(rows[0]).toHaveTextContent('BTN')
    expect(rows[0]).toHaveTextContent('−2.5 bb')
    expect(rows[0]).toHaveTextContent('EV lost 3.17 bb')
    expect(rows[1]).toHaveTextContent('Hand 2')
    expect(rows[1]).toHaveTextContent('BB')
    expect(rows[1]).toHaveTextContent('+2.5 bb')
    expect(rows[1]).not.toHaveTextContent('EV lost')
  })

  it('the button reads Review for an analysed hand and Analyse otherwise', async () => {
    setup()
    const rows = await screen.findAllByRole('listitem')
    expect(within(rows[0]!).getByRole('button')).toHaveTextContent('Review')
    expect(within(rows[1]!).getByRole('button')).toHaveTextContent('Analyse')
  })

  it('has no button for a hand with no decision', async () => {
    const hands = playHandsFixture()
    setup([{ ...hands[1]!, decision_count: 0, ev_loss_bb: null, analysed: false }])
    const rows = await screen.findAllByRole('listitem')
    expect(within(rows[0]!).queryByRole('button')).toBeNull()
  })

  it('has no button for a hand that is still running', async () => {
    const hands = playHandsFixture()
    setup([{ ...hands[1]!, ended_by: null, result_bb: null }])
    const rows = await screen.findAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('In progress')
    expect(within(rows[0]!).queryByRole('button')).toBeNull()
  })

  it('clicking calls onOpen with the hand id', async () => {
    const { onOpen, user } = setup()
    const rows = await screen.findAllByRole('listitem')
    await user.click(within(rows[1]!).getByRole('button'))
    expect(onOpen).toHaveBeenCalledWith(playHandsFixture()[1]!.id)
  })

  it('says so when there are no hands, and when the load fails', async () => {
    setup([])
    expect(await screen.findByText('No hands yet.')).toBeInTheDocument()
  })
})
