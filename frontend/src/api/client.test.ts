import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  currentPuzzle,
  getAttempt,
  getHistory,
  getPuzzle,
  getSettings,
  getStats,
  health,
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
})
