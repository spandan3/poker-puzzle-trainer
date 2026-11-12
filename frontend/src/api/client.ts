import { formatDetail } from '../lib/format'
import type {
  AttemptIn,
  AttemptResult,
  AttemptSummary,
  Explanation,
  Health,
  HistoryPage,
  NewPuzzleIn,
  PuzzleView,
  SettingsPatch,
  SettingsView,
  StatsView,
  StreetName,
} from './types'

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(detail === undefined ? `request failed (${status})` : formatDetail(detail))
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function readBody(res: Response): Promise<unknown> {
  const text = await res.text()
  if (text === '') return undefined
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const init: RequestInit = { method }
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  try {
    return await fetch(path, init)
  } catch (cause) {
    throw new ApiError(0, cause instanceof Error ? cause.message : 'network error')
  }
}

async function failure(res: Response): Promise<ApiError> {
  const data = await readBody(res)
  const detail =
    typeof data === 'object' && data !== null && 'detail' in data
      ? (data as { detail: unknown }).detail
      : undefined
  return new ApiError(res.status, detail)
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await send(method, path, body)
  if (!res.ok) throw await failure(res)
  return (await readBody(res)) as T
}

export function health(): Promise<Health> {
  return request('GET', '/api/health')
}

/** The unanswered puzzle to resume, or `null` when there is none (404). */
export async function currentPuzzle(): Promise<PuzzleView | null> {
  const res = await send('GET', '/api/puzzles/current')
  if (res.status === 404) return null
  if (!res.ok) throw await failure(res)
  return (await readBody(res)) as PuzzleView
}

export function newPuzzle(body: NewPuzzleIn): Promise<PuzzleView> {
  return request('POST', '/api/puzzles', body)
}

export function getPuzzle(id: number): Promise<PuzzleView> {
  return request('GET', `/api/puzzles/${id}`)
}

export function submitAttempt(id: number, body: AttemptIn): Promise<AttemptResult> {
  return request('POST', `/api/puzzles/${id}/attempts`, body)
}

export function getSettings(): Promise<SettingsView> {
  return request('GET', '/api/settings')
}

export function patchSettings(body: SettingsPatch): Promise<SettingsView> {
  return request('PATCH', '/api/settings', body)
}

/** `GET /api/stats`: the day boundary follows `tz` (an IANA zone). A 422 means the server doesn't know the zone. */
export function getStats(tz: string): Promise<StatsView> {
  return request('GET', `/api/stats?tz=${encodeURIComponent(tz)}`)
}

/** The filters of `GET /api/history`; unset or `null` ones are left out of the query. */
export interface HistoryParams {
  limit?: number
  offset?: number
  first_only?: boolean
  street?: StreetName | null
  verdict?: AttemptSummary['verdict'] | null
  action_kind?: AttemptSummary['action_kind'] | null
  profile?: string | null
}

export function getHistory(params: HistoryParams = {}): Promise<HistoryPage> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) query.set(key, String(value))
  }
  const qs = query.toString()
  return request('GET', qs === '' ? '/api/history' : `/api/history?${qs}`)
}

/** A stored result, as `POST .../attempts` returned it. */
export function getAttempt(id: number): Promise<AttemptResult> {
  return request('GET', `/api/attempts/${id}`)
}

/** The explanation of a stored attempt, reworded by the local model when one is set up. */
export async function getExplanation(
  attemptId: number,
  signal?: AbortSignal,
): Promise<Explanation> {
  let res: Response
  try {
    res = await fetch(`/api/attempts/${attemptId}/explanation`, { method: 'GET', signal })
  } catch (cause) {
    if (signal?.aborted) throw cause
    throw new ApiError(0, cause instanceof Error ? cause.message : 'network error')
  }
  if (!res.ok) throw await failure(res)
  return (await readBody(res)) as Explanation
}
