import { useEffect, useState } from 'react'
import * as client from '../api/client'
import type { AttemptResult, Explanation, SettingsView } from '../api/types'

export type LlmSettings = Pick<SettingsView, 'llm_status' | 'llm_model' | 'llm_detail'>

export interface ExplanationState {
  /** What to show now: the template until the local model's version arrives. */
  explanation: Explanation
  /** The model's name while its rewrite is being fetched, else `null`. */
  pendingModel: string | null
  /** The request for the rewrite failed: the template stays. */
  requestFailed: boolean
}

type Fetcher = (attemptId: number, signal: AbortSignal) => Promise<Explanation>

type Outcome = { attemptId: number; explanation: Explanation } | { attemptId: number; failed: true }

/**
 * The explanation to show for a result. Off or unavailable: the one inside the result, no request.
 * Ready: the same until `GET /api/attempts/{id}/explanation` answers; the request is aborted when
 * the result changes or the component unmounts, and an answer is used only for its own attempt.
 */
export function useExplanation(
  result: AttemptResult | null,
  llm: LlmSettings | null,
  fetchExplanation: Fetcher = client.getExplanation,
): ExplanationState | null {
  const attemptId = result?.attempt.id ?? null
  const ready = llm?.llm_status === 'ready'
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  useEffect(() => {
    if (attemptId === null || !ready) return
    const controller = new AbortController()
    fetchExplanation(attemptId, controller.signal).then(
      (explanation) => {
        if (!controller.signal.aborted) setOutcome({ attemptId, explanation })
      },
      () => {
        if (!controller.signal.aborted) setOutcome({ attemptId, failed: true })
      },
    )
    return () => controller.abort()
  }, [attemptId, ready, fetchExplanation])

  if (result === null) return null
  const mine = outcome !== null && outcome.attemptId === attemptId ? outcome : null
  if (!ready) {
    return { explanation: result.explanation, pendingModel: null, requestFailed: false }
  }
  if (mine !== null && 'explanation' in mine) {
    return { explanation: mine.explanation, pendingModel: null, requestFailed: false }
  }
  const failed = mine !== null
  return {
    explanation: result.explanation,
    pendingModel: failed ? null : (llm?.llm_model ?? 'the local model'),
    requestFailed: failed,
  }
}
