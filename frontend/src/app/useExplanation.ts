import { useEffect, useRef, useState } from 'react'
import type { Explanation, SettingsView } from '../api/types'

export type LlmSettings = Pick<SettingsView, 'llm_status' | 'llm_model' | 'llm_detail'>

export interface ExplanationState {
  /** What to show now: the template until the local model's version arrives. */
  explanation: Explanation
  /** The model's name while its rewrite is being fetched, else `null`. */
  pendingModel: string | null
  /** The request for the rewrite failed: the template stays. */
  requestFailed: boolean
}

export type ExplanationKey = string | number

type Outcome =
  { key: ExplanationKey; explanation: Explanation } | { key: ExplanationKey; failed: true }

/**
 * The explanation to show for a decision. Off or unavailable: the `template`, no request.
 * Ready: the same until `fetcher` answers; the request is aborted when `key` changes or the
 * component unmounts, and an answer is used only for its own key. `key` is null when there is
 * nothing to explain yet (the hook then returns null). The fetcher is read through a ref, so an
 * inline function does not refetch; only a new `key` does.
 */
export function useExplanation(
  key: ExplanationKey | null,
  template: Explanation | null,
  fetcher: (signal: AbortSignal) => Promise<Explanation>,
  llm: LlmSettings | null,
): ExplanationState | null {
  const ready = llm?.llm_status === 'ready'
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  })

  useEffect(() => {
    if (key === null || !ready) return
    const controller = new AbortController()
    fetcherRef.current(controller.signal).then(
      (explanation) => {
        if (!controller.signal.aborted) setOutcome({ key, explanation })
      },
      () => {
        if (!controller.signal.aborted) setOutcome({ key, failed: true })
      },
    )
    return () => controller.abort()
  }, [key, ready])

  if (key === null || template === null) return null
  const mine = outcome !== null && outcome.key === key ? outcome : null
  if (!ready) {
    return { explanation: template, pendingModel: null, requestFailed: false }
  }
  if (mine !== null && 'explanation' in mine) {
    return { explanation: mine.explanation, pendingModel: null, requestFailed: false }
  }
  const failed = mine !== null
  return {
    explanation: template,
    pendingModel: failed ? null : (llm?.llm_model ?? 'the local model'),
    requestFailed: failed,
  }
}
