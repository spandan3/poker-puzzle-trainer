import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  currentPlaySession,
  currentPuzzle,
  endPlaySession,
  getAttempt,
  getExplanation,
  getHistory,
  getPuzzle,
  getSettings,
  getStats,
  health,
  listPlaySessions,
  nextPlayHand,
  playAction,
  startPlaySession,
  newPuzzle,
  patchSettings,
  submitAttempt,
} from './client'

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  vi.unstubAllGlobals()
})

function lastCall() {
  const [url, init] = fetchMock.mock.calls.at(-1)!
  return { url: String(url), init: init ?? {} }
}

describe('client', () => {
  it('gets health', async () => {
    fetchMock.mockResolvedValue(reply(200, { status: 'ok', version: '0.1.0' }))
    expect(await health()).toEqual({ status: 'ok', version: '0.1.0' })
    expect(lastCall().url).toBe('/api/health')
  })

  it('posts a JSON body with a content type', async () => {
    fetchMock.mockResolvedValue(reply(201, { id: 5 }))
    await newPuzzle({ street: 'flop' })
    const { url, init } = lastCall()
    expect(url).toBe('/api/puzzles')
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ street: 'flop' }))
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
  })

  it('submits an attempt to the puzzle', async () => {
    fetchMock.mockResolvedValue(reply(201, { id: 1 }))
    await submitAttempt(12, { equity_guess: 0.4, option: 2 })
    const { url, init } = lastCall()
    expect(url).toBe('/api/puzzles/12/attempts')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ equity_guess: 0.4, option: 2 })
  })

  it('gets a puzzle and settings, and patches settings', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(reply(200, {})))
    await getPuzzle(3)
    expect(lastCall().url).toBe('/api/puzzles/3')
    await getSettings()
    expect(lastCall().url).toBe('/api/settings')
    await patchSettings({ show_pot_odds: false })
    const { url, init } = lastCall()
    expect(url).toBe('/api/settings')
    expect(init.method).toBe('PATCH')
    expect(init.body).toBe(JSON.stringify({ show_pot_odds: false }))
  })

  it('resolves null when there is no current puzzle', async () => {
    fetchMock.mockResolvedValue(reply(404, { detail: 'no current puzzle' }))
    expect(await currentPuzzle()).toBeNull()
    expect(lastCall().url).toBe('/api/puzzles/current')
  })

  it('returns the current puzzle', async () => {
    fetchMock.mockResolvedValue(reply(200, { id: 9 }))
    expect(await currentPuzzle()).toEqual({ id: 9 })
  })

  it('turns a non-2xx response into an ApiError with the detail', async () => {
    fetchMock.mockResolvedValue(reply(409, { detail: 'already answered' }))
    const err = await submitAttempt(1, { equity_guess: 0.5, option: 0 }).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(409)
    expect((err as ApiError).detail).toBe('already answered')
  })

  it('keeps a validation array as the detail', async () => {
    const detail = [{ loc: ['body'], msg: 'bad', type: 't' }]
    fetchMock.mockResolvedValue(reply(422, { detail }))
    const err = await newPuzzle({}).catch((e: unknown) => e)
    expect((err as ApiError).status).toBe(422)
    expect((err as ApiError).detail).toEqual(detail)
  })

  it('copes with a non-JSON error body', async () => {
    fetchMock.mockResolvedValue(new Response('<html>bad gateway</html>', { status: 502 }))
    const err = await health().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(502)
  })

  it('turns a network failure into an ApiError with status 0', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const err = await health().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(0)
  })

  it('treats a network failure on currentPuzzle as an error, not null', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(currentPuzzle()).rejects.toBeInstanceOf(ApiError)
  })

  it('gets stats for a time zone, encoded', async () => {
    fetchMock.mockResolvedValue(reply(200, {}))
    await getStats('Europe/London')
    expect(lastCall().url).toBe('/api/stats?tz=Europe%2FLondon')
  })

  it('gets history with only the filters that are set', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(reply(200, {})))
    await getHistory()
    expect(lastCall().url).toBe('/api/history')
    await getHistory({ limit: 25, offset: 50, street: 'river', verdict: null, first_only: false })
    expect(lastCall().url).toBe('/api/history?limit=25&offset=50&street=river&first_only=false')
  })

  it('gets a stored attempt', async () => {
    fetchMock.mockResolvedValue(reply(200, {}))
    await getAttempt(7)
    expect(lastCall().url).toBe('/api/attempts/7')
  })

  it('gets the explanation of an attempt, passing the abort signal', async () => {
    fetchMock.mockResolvedValue(reply(200, { headline: 'x' }))
    const controller = new AbortController()
    expect(await getExplanation(7, controller.signal)).toEqual({ headline: 'x' })
    expect(lastCall().url).toBe('/api/attempts/7/explanation')
    expect(lastCall().init?.signal).toBe(controller.signal)
  })

  it('throws an ApiError for a failed explanation request', async () => {
    fetchMock.mockResolvedValue(reply(404, { detail: 'no such attempt' }))
    await expect(getExplanation(7)).rejects.toMatchObject({ status: 404 })
  })

  describe('play', () => {
    it('reads the current session, or null on a 404', async () => {
      fetchMock.mockResolvedValueOnce(reply(404, { detail: 'none' }))
      expect(await currentPlaySession()).toBeNull()
      expect(lastCall().url).toBe('/api/play/sessions/current')
      fetchMock.mockResolvedValueOnce(reply(200, { id: 3 }))
      expect(await currentPlaySession()).toEqual({ id: 3 })
    })

    it('starts, ends and deals', async () => {
      fetchMock.mockImplementation(async () => reply(201, { id: 3 }))
      await startPlaySession()
      expect(lastCall().url).toBe('/api/play/sessions')
      expect(lastCall().init.method).toBe('POST')
      await endPlaySession(3)
      expect(lastCall().url).toBe('/api/play/sessions/3/end')
      await nextPlayHand(3, { top_up: true, expected_hands: 4 })
      expect(lastCall().url).toBe('/api/play/sessions/3/hands')
      expect(lastCall().init.body).toBe(JSON.stringify({ top_up: true, expected_hands: 4 }))
    })

    it('acts and lists', async () => {
      fetchMock.mockImplementation(async () => reply(200, { id: 3 }))
      await playAction(9, { expected_actions: 2, option: 1 })
      expect(lastCall().url).toBe('/api/play/hands/9/actions')
      expect(lastCall().init.body).toBe(JSON.stringify({ expected_actions: 2, option: 1 }))
      fetchMock.mockImplementation(async () => reply(200, []))
      expect(await listPlaySessions()).toEqual([])
      expect(lastCall().url).toBe('/api/play/sessions')
    })

    it('throws an ApiError carrying the status on a 409', async () => {
      fetchMock.mockResolvedValue(reply(409, { detail: 'stale' }))
      await expect(playAction(9, { expected_actions: 2, option: 1 })).rejects.toMatchObject({
        status: 409,
      })
    })
  })
})
