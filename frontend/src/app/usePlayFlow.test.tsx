import { StrictMode } from 'react'
import type { ReactNode } from 'react'
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { PlaySessionView } from '../api/types'
import { playSessionFixture, playSessionsFixture } from '../test/fixture'
import type { PlayApi } from './usePlayFlow'
import { BOT_PAUSE_MS, usePlayFlow } from './usePlayFlow'

const TO_ACT = playSessionFixture('hero_to_act')
// the hand after Hero's action: the bot's entries 4 to 8 follow, and the hand ends
const OVER = playSessionFixture('hand_over_showdown')
const NEXT_HAND: PlaySessionView = {
  ...TO_ACT,
  hands_played: 1,
  hand: { ...TO_ACT.hand!, id: 2, hand_no: 2 },
}

function fakeApi(overrides: Partial<PlayApi> = {}) {
  return {
    currentPlaySession: vi.fn<PlayApi['currentPlaySession']>(async () => null),
    startPlaySession: vi.fn<PlayApi['startPlaySession']>(async () => TO_ACT),
    endPlaySession: vi.fn<PlayApi['endPlaySession']>(async () => ({ ...TO_ACT, open: false })),
    nextPlayHand: vi.fn<PlayApi['nextPlayHand']>(async () => NEXT_HAND),
    playAction: vi.fn<PlayApi['playAction']>(async () => OVER),
    listPlaySessions: vi.fn<PlayApi['listPlaySessions']>(async () => playSessionsFixture()),
    ...overrides,
  }
}

const strict = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>

async function setup(api: PlayApi) {
  const hook = renderHook(() => usePlayFlow(api), { wrapper: strict })
  await flush()
  return hook
}

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('loading', () => {
  it('no open session: idle, with the past sessions', async () => {
    const api = fakeApi()
    const { result } = await setup(api)
    expect(result.current.state.kind).toBe('idle')
    expect(result.current.session).toBeNull()
    expect(result.current.past).toEqual(playSessionsFixture())
    expect(api.currentPlaySession).toHaveBeenCalledTimes(1)
  })

  it('a session loaded mid-hand shows its whole history at once', async () => {
    const api = fakeApi({ currentPlaySession: vi.fn(async () => TO_ACT) })
    const { result } = await setup(api)
    expect(result.current.state.kind).toBe('playing')
    expect(result.current.shownCount).toBe(TO_ACT.hand!.table.history.length)
    expect(result.current.revealing).toBe(false)
  })

  it('a finished hand loaded from the server is hand over, with no reveal', async () => {
    const api = fakeApi({ currentPlaySession: vi.fn(async () => OVER) })
    const { result } = await setup(api)
    expect(result.current.state.kind).toBe('handOver')
    expect(result.current.revealing).toBe(false)
  })

  it('does not load while disabled, then loads once', async () => {
    const api = fakeApi()
    const { rerender } = renderHook(({ enabled }) => usePlayFlow(api, { enabled }), {
      initialProps: { enabled: false },
    })
    await flush()
    expect(api.currentPlaySession).not.toHaveBeenCalled()
    rerender({ enabled: true })
    await flush()
    rerender({ enabled: true })
    expect(api.currentPlaySession).toHaveBeenCalledTimes(1)
  })
})

describe('start and act', () => {
  it('start gives a playing session', async () => {
    const api = fakeApi()
    const { result } = await setup(api)
    await act(async () => result.current.start())
    await flush()
    expect(result.current.state.kind).toBe('playing')
    expect(result.current.session?.id).toBe(TO_ACT.id)
  })

  it('a 409 on start loads the open session', async () => {
    const current = vi.fn<PlayApi['currentPlaySession']>().mockResolvedValueOnce(null)
    const api = fakeApi({
      currentPlaySession: current,
      startPlaySession: vi.fn(async () => {
        throw new ApiError(409, 'a session is open')
      }),
    })
    const { result } = await setup(api)
    current.mockResolvedValue(TO_ACT)
    await act(async () => result.current.start())
    await flush()
    expect(result.current.state.kind).toBe('playing')
  })

  it('act sends the choice with the hand’s action_count, then reveals the bot one entry per 600 ms', async () => {
    const api = fakeApi({ currentPlaySession: vi.fn(async () => TO_ACT) })
    const { result } = await setup(api)
    await act(async () => result.current.act({ option: 1 }))
    await flush()
    expect(api.playAction).toHaveBeenCalledWith(TO_ACT.hand!.id, {
      expected_actions: TO_ACT.hand!.action_count,
      option: 1,
    })
    // Hero's own action counts as shown; the bot's entries follow one at a time
    const hero = TO_ACT.hand!.action_count + 1
    const total = OVER.hand!.table.history.length
    expect(result.current.shownCount).toBe(hero)
    expect(result.current.revealing).toBe(true)
    expect(result.current.state.kind).toBe('playing')
    await advance(BOT_PAUSE_MS - 1)
    expect(result.current.shownCount).toBe(hero)
    await advance(1)
    expect(result.current.shownCount).toBe(hero + 1)
    for (let n = hero + 1; n < total - 1; n++) await advance(BOT_PAUSE_MS)
    expect(result.current.revealing).toBe(true)
    expect(result.current.state.kind).toBe('playing')
    await advance(BOT_PAUSE_MS)
    expect(result.current.shownCount).toBe(total)
    expect(result.current.revealing).toBe(false)
    expect(result.current.state.kind).toBe('handOver')
  })

  it('a custom size is sent as custom_to', async () => {
    const api = fakeApi({ currentPlaySession: vi.fn(async () => TO_ACT) })
    const { result } = await setup(api)
    await act(async () => result.current.act({ custom_to: 12 }))
    expect(api.playAction).toHaveBeenCalledWith(TO_ACT.hand!.id, {
      expected_actions: TO_ACT.hand!.action_count,
      custom_to: 12,
    })
  })

  it('ignores act while revealing', async () => {
    const api = fakeApi({ currentPlaySession: vi.fn(async () => TO_ACT) })
    const { result } = await setup(api)
    await act(async () => result.current.act({ option: 1 }))
    await flush()
    expect(result.current.revealing).toBe(true)
    await act(async () => result.current.act({ option: 0 }))
    expect(api.playAction).toHaveBeenCalledTimes(1)
  })

  it('ignores a second act while the request is in flight', async () => {
    let resolve!: (view: PlaySessionView) => void
    const api = fakeApi({
      currentPlaySession: vi.fn(async () => TO_ACT),
      playAction: vi.fn(() => new Promise<PlaySessionView>((res) => (resolve = res))),
    })
    const { result } = await setup(api)
    await act(async () => {
      result.current.act({ option: 1 })
      result.current.act({ option: 1 })
    })
    expect(api.playAction).toHaveBeenCalledTimes(1)
    expect(result.current.busy).toBe(true)
    await act(async () => resolve(OVER))
    expect(result.current.busy).toBe(false)
  })

  it('a 409 on act reloads the current session', async () => {
    const current = vi.fn<PlayApi['currentPlaySession']>().mockResolvedValueOnce(TO_ACT)
    const api = fakeApi({
      currentPlaySession: current,
      playAction: vi.fn(async () => {
        throw new ApiError(409, 'the hand moved on')
      }),
    })
    const { result } = await setup(api)
    current.mockResolvedValue(OVER)
    await act(async () => result.current.act({ option: 1 }))
    await flush()
    expect(api.currentPlaySession).toHaveBeenCalledTimes(2)
    expect(result.current.state.kind).toBe('handOver')
    expect(result.current.revealing).toBe(false)
  })

  it('another API error gives the error state, and retry reloads the session', async () => {
    const api = fakeApi({
      currentPlaySession: vi.fn(async () => TO_ACT),
      playAction: vi.fn(async () => {
        throw new ApiError(500, 'boom')
      }),
    })
    const { result } = await setup(api)
    await act(async () => result.current.act({ option: 1 }))
    await flush()
    const state = result.current.state
    expect(state.kind).toBe('error')
    // what was on screen stays
    expect(result.current.session?.id).toBe(TO_ACT.id)
    await act(async () => result.current.retry())
    await flush()
    expect(result.current.state.kind).toBe('playing')
  })

  it('a failed first load is an error, and retry loads again', async () => {
    const api = fakeApi({
      currentPlaySession: vi
        .fn<PlayApi['currentPlaySession']>()
        .mockRejectedValueOnce(new ApiError(0, 'Failed to fetch'))
        .mockResolvedValue(null),
    })
    const { result } = await setup(api)
    expect(result.current.state.kind).toBe('error')
    await act(async () => result.current.retry())
    await flush()
    expect(result.current.state.kind).toBe('idle')
  })
})

describe('next hand and end', () => {
  it('nextHand deals with top_up and the hands played so far, then reveals from the start', async () => {
    const api = fakeApi({ currentPlaySession: vi.fn(async () => OVER) })
    const { result } = await setup(api)
    await act(async () => result.current.nextHand(true))
    await flush()
    expect(api.nextPlayHand).toHaveBeenCalledWith(OVER.id, {
      top_up: true,
      expected_hands: OVER.hands_played,
    })
    expect(result.current.state.kind).toBe('playing')
    expect(result.current.session?.hand?.id).toBe(2)
  })

  it('nextHand is ignored while a hand is running', async () => {
    const api = fakeApi({ currentPlaySession: vi.fn(async () => TO_ACT) })
    const { result } = await setup(api)
    await act(async () => result.current.nextHand(false))
    expect(api.nextPlayHand).not.toHaveBeenCalled()
  })

  it('a bot that acts first is revealed from the first entry', async () => {
    const botFirst: PlaySessionView = {
      ...NEXT_HAND,
      hand: { ...OVER.hand!, id: 3, status: 'in_progress', outcome: null },
    }
    const api = fakeApi({
      currentPlaySession: vi.fn(async () => OVER),
      nextPlayHand: vi.fn(async () => botFirst),
    })
    const { result } = await setup(api)
    await act(async () => result.current.nextHand(false))
    await flush()
    expect(result.current.shownCount).toBe(0)
    expect(result.current.revealing).toBe(true)
    await advance(BOT_PAUSE_MS)
    expect(result.current.shownCount).toBe(1)
  })

  it('end goes back to idle and refreshes the past sessions', async () => {
    const api = fakeApi({ currentPlaySession: vi.fn(async () => TO_ACT) })
    const { result } = await setup(api)
    await act(async () => result.current.end())
    await flush()
    expect(api.endPlaySession).toHaveBeenCalledWith(TO_ACT.id)
    expect(result.current.state.kind).toBe('idle')
    expect(result.current.session).toBeNull()
    expect(api.listPlaySessions).toHaveBeenCalledTimes(1)
  })
})
