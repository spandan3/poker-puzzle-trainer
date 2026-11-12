import { StrictMode } from 'react'
import type { ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { AttemptIn, AttemptResult, PuzzleView, SettingsView } from '../api/types'
import { attemptFixture, puzzleFixture, settingsFixture } from '../test/fixture'
import type { FlowApi } from './usePuzzleFlow'
import { GENERATION_FAILED, SETTINGS_FAILED, SKIP_CONFIRM_MS, usePuzzleFlow } from './usePuzzleFlow'

const STALE =
  'Villain model changed since this puzzle was generated; custom sizes are disabled for this puzzle'

const BODY: AttemptIn = { equity_guess: 0.5, option: 1 }

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (error: unknown) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function withId(view: PuzzleView, id: number): PuzzleView {
  return { ...view, id }
}

/** A spying fake API: every method is a `vi.fn`, answering from fixtures by default. */
function fakeApi(overrides: Partial<FlowApi> = {}) {
  let nextId = 100
  const api = {
    currentPuzzle: vi.fn<FlowApi['currentPuzzle']>(async () => null),
    newPuzzle: vi.fn<FlowApi['newPuzzle']>(async () =>
      withId(puzzleFixture('flop_unopened'), nextId++),
    ),
    submitAttempt: vi.fn<FlowApi['submitAttempt']>(async () => attemptFixture('bet')),
    getSettings: vi.fn<FlowApi['getSettings']>(async () => settingsFixture()),
    patchSettings: vi.fn<FlowApi['patchSettings']>(async (patch) => ({
      ...settingsFixture(),
      ...patch,
    })),
    ...overrides,
  }
  return api
}

const strict = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>

function setup(api: FlowApi) {
  return renderHook(() => usePuzzleFlow(api), { wrapper: strict })
}

async function answering(result: ReturnType<typeof setup>['result']) {
  await waitFor(() => expect(result.current.state.kind).toBe('answering'))
  const state = result.current.state
  if (state.kind !== 'answering') throw new Error('not answering')
  return state
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('loading', () => {
  it('resumes the current puzzle: one GET, no POST, even under StrictMode', async () => {
    const view = puzzleFixture('turn')
    const api = fakeApi({ currentPuzzle: vi.fn(async () => view) })
    const { result } = setup(api)
    const state = await answering(result)
    expect(state.view).toBe(view)
    expect(api.currentPuzzle).toHaveBeenCalledTimes(1)
    expect(api.newPuzzle).not.toHaveBeenCalled()
    expect(api.getSettings).toHaveBeenCalledTimes(1)
  })

  it('posts one new puzzle when there is no current one (404), with the stored street', async () => {
    window.localStorage.setItem('ppt.street', 'river')
    const api = fakeApi()
    const { result } = setup(api)
    await answering(result)
    expect(api.currentPuzzle).toHaveBeenCalledTimes(1)
    expect(api.newPuzzle).toHaveBeenCalledTimes(1)
    expect(api.newPuzzle).toHaveBeenCalledWith({ street: 'river' })
    expect(result.current.street).toBe('river')
  })

  it('ignores a stored street that is not a street', async () => {
    window.localStorage.setItem('ppt.street', 'showdown')
    const api = fakeApi()
    const { result } = setup(api)
    await answering(result)
    expect(api.newPuzzle).toHaveBeenCalledWith({ street: null })
  })

  it('shows "couldn\'t generate" on 503, and Retry loads again', async () => {
    const api = fakeApi({
      newPuzzle: vi
        .fn<FlowApi['newPuzzle']>()
        .mockRejectedValueOnce(new ApiError(503, 'generation failed'))
        .mockResolvedValueOnce(puzzleFixture('river')),
    })
    const { result } = setup(api)
    await waitFor(() => expect(result.current.state.kind).toBe('error'))
    const state = result.current.state
    if (state.kind !== 'error') throw new Error()
    expect(state.message).toBe(GENERATION_FAILED)
    act(() => state.retry())
    const next = await answering(result)
    expect(next.view.street).toBe('river')
    // the retry resumes first, as the first load did
    expect(api.currentPuzzle).toHaveBeenCalledTimes(2)
  })

  it('reports a network failure with a retry', async () => {
    const api = fakeApi({
      currentPuzzle: vi.fn().mockRejectedValue(new ApiError(0, 'Failed to fetch')),
    })
    const { result } = setup(api)
    await waitFor(() => expect(result.current.state.kind).toBe('error'))
    const state = result.current.state
    if (state.kind !== 'error') throw new Error()
    expect(state.message).toMatch(/can't reach the server/i)
    expect(state.previous).toBeNull()
  })

  it('a settings failure on load is not an error: play goes on', async () => {
    const api = fakeApi({ getSettings: vi.fn().mockRejectedValue(new ApiError(0, 'down')) })
    const { result } = setup(api)
    await answering(result)
    expect(result.current.settings).toBeNull()
  })
})

describe('skip and next', () => {
  it('needs a second N to skip, within the confirmation window', async () => {
    const api = fakeApi()
    const { result } = setup(api)
    const first = await answering(result)
    act(() => result.current.requestSkip())
    expect(result.current.state).toMatchObject({ kind: 'answering', skipPending: true })
    expect(api.newPuzzle).toHaveBeenCalledTimes(1)
    act(() => result.current.requestSkip())
    const second = await answering(result)
    expect(second.view.id).not.toBe(first.view.id)
    expect(api.newPuzzle).toHaveBeenCalledTimes(2)
  })

  it('the skip prompt lapses after the window, and Escape cancels it', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const api = fakeApi()
    const { result } = setup(api)
    await answering(result)
    act(() => result.current.requestSkip())
    act(() => vi.advanceTimersByTime(SKIP_CONFIRM_MS + 1))
    expect(result.current.state).toMatchObject({ skipPending: false })
    act(() => result.current.requestSkip())
    act(() => result.current.cancelSkip())
    expect(result.current.state).toMatchObject({ skipPending: false })
    act(() => result.current.requestSkip())
    expect(result.current.state).toMatchObject({ skipPending: true })
    expect(api.newPuzzle).toHaveBeenCalledTimes(1)
  })

  it('N after a result loads the next puzzle at once; repeats send one request', async () => {
    const next = deferred<PuzzleView>()
    const api = fakeApi()
    const { result } = setup(api)
    await answering(result)
    act(() => result.current.submit(BODY))
    await waitFor(() => expect(result.current.state.kind).toBe('result'))
    vi.mocked(api.newPuzzle).mockReturnValueOnce(next.promise)
    act(() => {
      result.current.requestSkip()
      result.current.requestSkip()
    })
    act(() => result.current.newPuzzle())
    expect(api.newPuzzle).toHaveBeenCalledTimes(2)
    // while loading, what was shown is kept (no collapse)
    expect(result.current.state).toMatchObject({ kind: 'loading' })
    const state = result.current.state
    if (state.kind !== 'loading') throw new Error()
    expect(state.previous?.result).not.toBeNull()
    await act(async () => next.resolve(withId(puzzleFixture('river'), 7)))
    expect(result.current.state).toMatchObject({ kind: 'answering', view: { id: 7 } })
  })

  it('a new puzzle never resumes: only POST after the first load', async () => {
    const api = fakeApi()
    const { result } = setup(api)
    await answering(result)
    act(() => result.current.newPuzzle())
    await waitFor(() => expect(api.newPuzzle).toHaveBeenCalledTimes(2))
    expect(api.currentPuzzle).toHaveBeenCalledTimes(1)
  })

  it('setStreet stores the choice and the next POST uses it', async () => {
    const api = fakeApi()
    const { result } = setup(api)
    await answering(result)
    act(() => result.current.setStreet('turn'))
    expect(window.localStorage.getItem('ppt.street')).toBe('turn')
    act(() => result.current.newPuzzle())
    await waitFor(() => expect(api.newPuzzle).toHaveBeenLastCalledWith({ street: 'turn' }))
    act(() => result.current.setStreet(null))
    expect(window.localStorage.getItem('ppt.street')).toBeNull()
  })
})

describe('submit', () => {
  it('submits once and shows the result', async () => {
    const pending = deferred<AttemptResult>()
    const api = fakeApi({ submitAttempt: vi.fn(() => pending.promise) })
    const { result } = setup(api)
    const state = await answering(result)
    act(() => {
      result.current.submit(BODY)
      result.current.submit(BODY)
    })
    expect(result.current.state.kind).toBe('submitting')
    // nothing else happens while submitting: no skip, no new puzzle
    act(() => {
      result.current.requestSkip()
      result.current.newPuzzle()
    })
    expect(api.newPuzzle).toHaveBeenCalledTimes(1)
    await act(async () => pending.resolve(attemptFixture('bet')))
    expect(api.submitAttempt).toHaveBeenCalledTimes(1)
    expect(api.submitAttempt).toHaveBeenCalledWith(state.view.id, BODY)
    expect(result.current.state).toMatchObject({ kind: 'result', view: state.view })
  })

  it('409 "Villain model changed" shows the error and disables custom sizes', async () => {
    const api = fakeApi({ submitAttempt: vi.fn().mockRejectedValue(new ApiError(409, STALE)) })
    const { result } = setup(api)
    await answering(result)
    act(() => result.current.submit({ equity_guess: 0.5, custom_to: 9 }))
    await waitFor(() =>
      expect(result.current.state).toMatchObject({
        kind: 'answering',
        error: STALE,
        customDisabledReason: STALE,
      }),
    )
  })

  it('another 409 (a concurrent submit) shows the error but keeps custom sizes', async () => {
    const api = fakeApi({
      submitAttempt: vi.fn().mockRejectedValue(new ApiError(409, 'concurrent submit, try again')),
    })
    const { result } = setup(api)
    await answering(result)
    act(() => result.current.submit({ equity_guess: 0.5, custom_to: 9 }))
    await waitFor(() =>
      expect(result.current.state).toMatchObject({
        kind: 'answering',
        error: 'concurrent submit, try again',
        customDisabledReason: null,
      }),
    )
  })

  it('a disabled custom size stays disabled after a later, different error', async () => {
    const api = fakeApi({
      submitAttempt: vi
        .fn()
        .mockRejectedValueOnce(new ApiError(409, STALE))
        .mockRejectedValueOnce(new ApiError(422, [{ msg: 'bad equity' }])),
    })
    const { result } = setup(api)
    await answering(result)
    act(() => result.current.submit({ equity_guess: 0.5, custom_to: 9 }))
    await waitFor(() => expect(result.current.state).toMatchObject({ error: STALE }))
    act(() => result.current.submit(BODY))
    await waitFor(() =>
      expect(result.current.state).toMatchObject({
        error: 'bad equity',
        customDisabledReason: STALE,
      }),
    )
  })

  it('422 keeps the answer for editing with the validation messages', async () => {
    const api = fakeApi({
      submitAttempt: vi.fn().mockRejectedValue(new ApiError(422, [{ msg: 'one' }, { msg: 'two' }])),
    })
    const { result } = setup(api)
    await answering(result)
    act(() => result.current.submit(BODY))
    await waitFor(() =>
      expect(result.current.state).toMatchObject({ kind: 'answering', error: 'one; two' }),
    )
  })

  it('a network failure returns to answering: submitting again sends the current answer', async () => {
    const api = fakeApi({
      submitAttempt: vi
        .fn<FlowApi['submitAttempt']>()
        .mockRejectedValueOnce(new ApiError(0, 'Failed to fetch'))
        .mockResolvedValueOnce(attemptFixture('fold')),
    })
    const { result } = setup(api)
    const state = await answering(result)
    act(() => result.current.submit(BODY))
    await waitFor(() =>
      expect(result.current.state).toMatchObject({
        kind: 'answering',
        error: expect.stringMatching(/answer is kept/) as unknown,
      }),
    )
    // no automatic resend: the user edits and submits, and that body is what is sent
    const edited: AttemptIn = { equity_guess: 0.3, option: 0 }
    act(() => result.current.submit(edited))
    await waitFor(() => expect(result.current.state.kind).toBe('result'))
    expect(api.submitAttempt).toHaveBeenCalledTimes(2)
    expect(api.submitAttempt).toHaveBeenLastCalledWith(state.view.id, edited)
  })
})

describe('settings', () => {
  it('patches a setting and keeps the server view', async () => {
    const api = fakeApi()
    const { result } = setup(api)
    await waitFor(() => expect(result.current.settings).not.toBeNull())
    act(() => result.current.setSetting({ show_pot_odds: false }))
    expect(result.current.settings?.show_pot_odds).toBe(false)
    expect(api.patchSettings).toHaveBeenCalledWith({ show_pot_odds: false })
    await waitFor(() => expect(result.current.notice).toBeNull())
  })

  it('a failed save reverts the control and warns', async () => {
    const save = deferred<SettingsView>()
    const api = fakeApi({ patchSettings: vi.fn(() => save.promise) })
    const { result } = setup(api)
    await waitFor(() => expect(result.current.settings).not.toBeNull())
    act(() => result.current.setSetting({ profile: 'lag' }))
    expect(result.current.settings?.profile).toBe('lag')
    await act(async () => save.reject(new ApiError(0, 'down')))
    expect(result.current.settings?.profile).toBeNull()
    expect(result.current.notice).toBe(SETTINGS_FAILED)
    act(() => result.current.dismissNotice())
    expect(result.current.notice).toBeNull()
  })

  it('an older failed save does not revert a newer one', async () => {
    const first = deferred<SettingsView>()
    const second = deferred<SettingsView>()
    const api = fakeApi({
      patchSettings: vi
        .fn<FlowApi['patchSettings']>()
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise),
    })
    const { result } = setup(api)
    await waitFor(() => expect(result.current.settings).not.toBeNull())
    act(() => result.current.setSetting({ show_pot_odds: false }))
    act(() => result.current.setSetting({ show_pot_odds: true }))
    await act(async () => second.resolve({ ...settingsFixture(), show_pot_odds: true }))
    await act(async () => first.reject(new ApiError(0, 'down')))
    expect(result.current.settings?.show_pot_odds).toBe(true)
    expect(result.current.notice).toBeNull()
  })
})
