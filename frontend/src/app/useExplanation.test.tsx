import { StrictMode } from 'react'
import type { ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AttemptResult, Explanation } from '../api/types'
import { attemptFixture, explanationLlmFixture } from '../test/fixture'
import type { LlmSettings } from './useExplanation'
import { useExplanation } from './useExplanation'

const strict = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>

const off: LlmSettings = { llm_status: 'off', llm_model: null, llm_detail: null }
const unavailable: LlmSettings = {
  llm_status: 'unavailable',
  llm_model: 'llama3.2:3b',
  llm_detail: 'Ollama is not running',
}
const ready: LlmSettings = { llm_status: 'ready', llm_model: 'llama3.2:3b', llm_detail: null }

function withId(result: AttemptResult, id: number): AttemptResult {
  return { ...result, attempt: { ...result.attempt, id } }
}

interface Pending {
  attemptId: number
  signal: AbortSignal
  resolve: (e: Explanation) => void
  reject: (e: unknown) => void
}

function fakeFetch() {
  const pending: Pending[] = []
  const fn = vi.fn(
    (attemptId: number, signal: AbortSignal) =>
      new Promise<Explanation>((resolve, reject) => {
        pending.push({ attemptId, signal, resolve, reject })
      }),
  )
  return { fn, pending }
}

/** The puzzle call site's shape: key and template from the result, the fetcher bound to its id. */
function useResult(
  result: AttemptResult | null,
  llm: LlmSettings | null,
  fn: (attemptId: number, signal: AbortSignal) => Promise<Explanation>,
) {
  const id = result?.attempt.id ?? null
  return useExplanation(id, result?.explanation ?? null, (signal) => fn(id as number, signal), llm)
}

describe('useExplanation', () => {
  it('shows the result’s own explanation and makes no request when the model is off', () => {
    const { fn } = fakeFetch()
    const result = attemptFixture('bet')
    const { result: hook } = renderHook(() => useResult(result, off, fn), { wrapper: strict })
    expect(hook.current).toEqual({
      explanation: result.explanation,
      pendingModel: null,
      requestFailed: false,
    })
    expect(fn).not.toHaveBeenCalled()
  })

  it('makes no request when the model is unavailable', () => {
    const { fn } = fakeFetch()
    const result = attemptFixture('bet')
    const { result: hook } = renderHook(() => useResult(result, unavailable, fn), {
      wrapper: strict,
    })
    expect(hook.current?.explanation).toBe(result.explanation)
    expect(hook.current?.pendingModel).toBeNull()
    expect(fn).not.toHaveBeenCalled()
  })

  it('fetches the rewrite once when the status changes from unavailable to ready', async () => {
    const { fn, pending } = fakeFetch()
    const result = attemptFixture('bet')
    const { result: hook, rerender } = renderHook(
      ({ llm }: { llm: LlmSettings }) => useResult(result, llm, fn),
      { wrapper: strict, initialProps: { llm: unavailable } },
    )
    expect(fn).not.toHaveBeenCalled()
    rerender({ llm: ready })
    expect(hook.current?.pendingModel).toBe('llama3.2:3b')
    // StrictMode's first effect is aborted; one live request remains
    expect(pending.filter((p) => !p.signal.aborted)).toHaveLength(1)
    const llm = explanationLlmFixture()
    await act(async () => {
      pending.forEach((p) => p.resolve(llm))
    })
    await waitFor(() => expect(hook.current?.explanation).toEqual(llm))
    // an unchanged status makes no second request
    const calls = fn.mock.calls.length
    rerender({ llm: { ...ready } })
    expect(fn.mock.calls.length).toBe(calls)
  })

  it('returns null without a result', () => {
    const { fn } = fakeFetch()
    const { result: hook } = renderHook(() => useResult(null, ready, fn))
    expect(hook.current).toBeNull()
    expect(fn).not.toHaveBeenCalled()
  })

  it('shows the template as pending, then swaps in the model’s version (StrictMode)', async () => {
    const { fn, pending } = fakeFetch()
    const result = attemptFixture('bet')
    const { result: hook } = renderHook(() => useResult(result, ready, fn), {
      wrapper: strict,
    })
    expect(hook.current?.explanation).toBe(result.explanation)
    expect(hook.current?.pendingModel).toBe('llama3.2:3b')
    // StrictMode's first effect was aborted; only the live request counts
    const live = pending.filter((p) => !p.signal.aborted)
    expect(live).toHaveLength(1)
    expect(live[0]!.attemptId).toBe(result.attempt.id)
    const llm = explanationLlmFixture()
    await act(async () => {
      pending.forEach((p) => p.resolve(llm))
    })
    await waitFor(() => expect(hook.current?.explanation).toEqual(llm))
    expect(hook.current?.pendingModel).toBeNull()
  })

  it('aborts the old request when the result changes and never swaps a stale answer', async () => {
    const { fn, pending } = fakeFetch()
    const a = withId(attemptFixture('bet'), 1)
    const b = withId(attemptFixture('call'), 2)
    const { result: hook, rerender } = renderHook(
      ({ r }: { r: AttemptResult }) => useResult(r, ready, fn),
      { initialProps: { r: a } },
    )
    const first = pending[0]!
    rerender({ r: b })
    expect(first.signal.aborted).toBe(true)
    expect(hook.current?.explanation).toBe(b.explanation)
    await act(async () => {
      first.resolve(explanationLlmFixture())
    })
    expect(hook.current?.explanation).toBe(b.explanation)
    expect(hook.current?.pendingModel).toBe('llama3.2:3b')
    const second = pending.find((p) => p.attemptId === 2)!
    const llm: Explanation = { ...explanationLlmFixture(), headline: 'For B' }
    await act(async () => {
      second.resolve(llm)
    })
    expect(hook.current?.explanation.headline).toBe('For B')
  })

  it('aborts on unmount', () => {
    const { fn, pending } = fakeFetch()
    const { unmount } = renderHook(() => useResult(attemptFixture('bet'), ready, fn))
    unmount()
    expect(pending[0]!.signal.aborted).toBe(true)
  })

  it('keeps the template and flags the failure when the request fails', async () => {
    const { fn, pending } = fakeFetch()
    const result = attemptFixture('bet')
    const { result: hook } = renderHook(() => useResult(result, ready, fn))
    await act(async () => {
      pending[0]!.reject(new Error('boom'))
    })
    expect(hook.current).toEqual({
      explanation: result.explanation,
      pendingModel: null,
      requestFailed: true,
    })
  })

  it('fetches once per string key with a custom fetcher', async () => {
    const calls: string[] = []
    const fetcher = (signal: AbortSignal) => {
      calls.push('x')
      void signal
      return Promise.resolve(explanationLlmFixture())
    }
    const template = attemptFixture('bet').explanation
    const { result: hook, rerender } = renderHook(
      ({ k }: { k: string | null }) => useExplanation(k, template, fetcher, ready),
      { initialProps: { k: '7:2' as string | null } },
    )
    await waitFor(() => expect(hook.current?.explanation).toEqual(explanationLlmFixture()))
    expect(calls).toHaveLength(1)
    rerender({ k: '7:2' })
    expect(calls).toHaveLength(1)
    rerender({ k: '7:3' })
    expect(hook.current?.explanation).toBe(template)
    await waitFor(() => expect(calls).toHaveLength(2))
  })

  it('does nothing for a null key', () => {
    const fetcher = vi.fn()
    const template = attemptFixture('bet').explanation
    const { result: hook } = renderHook(() => useExplanation(null, template, fetcher, ready))
    expect(hook.current).toBeNull()
    expect(fetcher).not.toHaveBeenCalled()
  })
})
