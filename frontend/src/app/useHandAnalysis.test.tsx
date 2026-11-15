import { StrictMode } from 'react'
import type { ReactNode } from 'react'
import { act, renderHook } from '@testing-library/react'
import type { Mock } from 'vitest'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { DecisionReview, HandAnalysis } from '../api/types'
import { playHandAnalysisFixture } from '../test/fixture'
import type { AnalysisApi } from './useHandAnalysis'
import { useHandAnalysis } from './useHandAnalysis'

const FULL = playHandAnalysisFixture()
const strict = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>

/** The fixture with only the decisions in `stored` (by index) filled in. */
function partial(stored: number[], handId = 1): HandAnalysis {
  return {
    ...FULL,
    hand_id: handId,
    summary: null,
    decisions: FULL.decisions.map((d, i) => (stored.includes(i) ? d : null)),
  }
}

type Fake = { [K in keyof AnalysisApi]: Mock<AnalysisApi[K]> }

function fakeApi(stored: number[], overrides: Partial<Fake> = {}): Fake {
  return {
    getPlayAnalysis: vi.fn<AnalysisApi['getPlayAnalysis']>(async (id) => {
      // once every decision has been posted the server has the summary
      return posted.length + stored.length === FULL.decisions.length
        ? { ...FULL, hand_id: id }
        : partial([...stored, ...posted], id)
    }),
    postPlayDecision: vi.fn<AnalysisApi['postPlayDecision']>(async (_id, n) => {
      posted.push(n)
      return FULL.decisions[n] as DecisionReview
    }),
    ...overrides,
  }
}
let posted: number[] = []

async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0))
  })
}

describe('useHandAnalysis', () => {
  it('GETs, then POSTs each missing decision in order and reports progress', async () => {
    posted = []
    const api = fakeApi([0, 1])
    const { result } = renderHook(() => useHandAnalysis(1, api), { wrapper: strict })
    expect(result.current.analysis).toBeNull()
    await flush()
    expect(api.postPlayDecision.mock.calls.map((c) => c[1])).toEqual([2, 3])
    expect(result.current.progress).toEqual({ done: 4, total: 4 })
    expect(result.current.analysis?.summary).not.toBeNull()
    expect(result.current.error).toBeNull()
  })

  it('does not post stored decisions again', async () => {
    posted = []
    const api = fakeApi([0, 1, 2, 3])
    const { result } = renderHook(() => useHandAnalysis(1, api))
    await flush()
    expect(api.postPlayDecision).not.toHaveBeenCalled()
    expect(api.getPlayAnalysis).toHaveBeenCalledTimes(1)
    expect(result.current.progress).toEqual({ done: 4, total: 4 })
  })

  it('posts one decision at a time', async () => {
    posted = []
    let open = 0
    let most = 0
    const api = fakeApi([], {
      postPlayDecision: vi.fn(async (_id: number, n: number) => {
        open += 1
        most = Math.max(most, open)
        await new Promise((r) => setTimeout(r, 1))
        open -= 1
        posted.push(n)
        return FULL.decisions[n] as DecisionReview
      }),
    })
    renderHook(() => useHandAnalysis(1, api))
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30))
    })
    expect(most).toBe(1)
    expect(api.postPlayDecision).toHaveBeenCalledTimes(4)
  })

  it('a failed post stops with an error, and retry continues from that decision', async () => {
    posted = []
    let fail = true
    const api = fakeApi([0], {
      postPlayDecision: vi.fn(async (_id: number, n: number) => {
        if (n === 2 && fail) throw new ApiError(500, 'solver died')
        posted.push(n)
        return FULL.decisions[n] as DecisionReview
      }),
    })
    const { result } = renderHook(() => useHandAnalysis(1, api))
    await flush()
    expect(result.current.error).toMatch(/solver died/)
    expect(result.current.progress).toEqual({ done: 2, total: 4 })
    expect(api.postPlayDecision.mock.calls.map((c) => c[1])).toEqual([1, 2])
    fail = false
    act(() => result.current.retry())
    await flush()
    expect(api.postPlayDecision.mock.calls.map((c) => c[1])).toEqual([1, 2, 2, 3])
    expect(result.current.error).toBeNull()
    expect(result.current.progress).toEqual({ done: 4, total: 4 })
  })

  it('a failed GET is an error with a retry', async () => {
    posted = []
    const api = fakeApi([0, 1, 2, 3], {
      getPlayAnalysis: vi
        .fn<AnalysisApi['getPlayAnalysis']>()
        .mockRejectedValueOnce(new ApiError(409, 'the hand is still running'))
        .mockResolvedValue(FULL),
    })
    const { result } = renderHook(() => useHandAnalysis(1, api))
    await flush()
    expect(result.current.error).toMatch(/still running/)
    act(() => result.current.retry())
    await flush()
    expect(result.current.error).toBeNull()
    expect(result.current.analysis).not.toBeNull()
  })

  it('a new hand id stops the loop and drops late responses', async () => {
    posted = []
    const late: ((r: DecisionReview) => void)[] = []
    const api = fakeApi([], {
      postPlayDecision: vi.fn(
        (_id: number, n: number) =>
          new Promise<DecisionReview>((resolve) => {
            late.push(() => resolve(FULL.decisions[n] as DecisionReview))
          }),
      ),
    })
    const { result, rerender } = renderHook(({ id }) => useHandAnalysis(id, api), {
      initialProps: { id: 1 },
    })
    await flush()
    expect(api.postPlayDecision).toHaveBeenCalledTimes(1)
    rerender({ id: 2 })
    await act(async () => late[0]!(FULL.decisions[0]!))
    await flush()
    // hand 1's first answer is dropped: no second post for hand 1, and nothing of it is shown
    expect(api.postPlayDecision.mock.calls.filter((c) => c[0] === 1)).toHaveLength(1)
    expect(result.current.analysis?.hand_id ?? 2).toBe(2)
    expect(result.current.progress.done).toBe(0)
  })

  it('unmounting stops the loop', async () => {
    posted = []
    let release: (() => void) | null = null
    const api = fakeApi([], {
      postPlayDecision: vi.fn(
        (_id: number, n: number) =>
          new Promise<DecisionReview>((resolve) => {
            release = () => resolve(FULL.decisions[n] as DecisionReview)
          }),
      ),
    })
    const { unmount } = renderHook(() => useHandAnalysis(1, api))
    await flush()
    unmount()
    await act(async () => release!())
    await flush()
    expect(api.postPlayDecision).toHaveBeenCalledTimes(1)
  })

  it('a hand with no Hero decision is complete at once', async () => {
    posted = []
    const api = fakeApi([], {
      getPlayAnalysis: vi.fn(async () => ({ ...FULL, decisions: [], summary: null })),
    })
    const { result } = renderHook(() => useHandAnalysis(1, api))
    await flush()
    expect(result.current.progress).toEqual({ done: 0, total: 0 })
    expect(api.postPlayDecision).not.toHaveBeenCalled()
  })
})
