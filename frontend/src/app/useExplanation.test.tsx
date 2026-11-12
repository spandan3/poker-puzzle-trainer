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

describe('useExplanation', () => {
  it('shows the result’s own explanation and makes no request when the model is off', () => {
    const { fn } = fakeFetch()
    const result = attemptFixture('bet')
    const { result: hook } = renderHook(() => useExplanation(result, off, fn), { wrapper: strict })
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
    const { result: hook } = renderHook(() => useExplanation(result, unavailable, fn), {
      wrapper: strict,
    })
    expect(hook.current?.explanation).toBe(result.explanation)
    expect(hook.current?.pendingModel).toBeNull()
    expect(fn).not.toHaveBeenCalled()
  })

  it('returns null without a result', () => {
    const { fn } = fakeFetch()
    const { result: hook } = renderHook(() => useExplanation(null, ready, fn))
    expect(hook.current).toBeNull()
    expect(fn).not.toHaveBeenCalled()
  })

  it('shows the template as pending, then swaps in the model’s version (StrictMode)', async () => {
    const { fn, pending } = fakeFetch()
    const result = attemptFixture('bet')
    const { result: hook } = renderHook(() => useExplanation(result, ready, fn), {
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
      ({ r }: { r: AttemptResult }) => useExplanation(r, ready, fn),
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
    const { unmount } = renderHook(() => useExplanation(attemptFixture('bet'), ready, fn))
    unmount()
    expect(pending[0]!.signal.aborted).toBe(true)
  })

  it('keeps the template and flags the failure when the request fails', async () => {
    const { fn, pending } = fakeFetch()
    const result = attemptFixture('bet')
    const { result: hook } = renderHook(() => useExplanation(result, ready, fn))
    await act(async () => {
      pending[0]!.reject(new Error('boom'))
    })
    expect(hook.current).toEqual({
      explanation: result.explanation,
      pendingModel: null,
      requestFailed: true,
    })
  })
})
