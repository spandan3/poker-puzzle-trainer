// The analysis of one finished hand: what is stored, then each missing decision graded one at a
// time in order (the server solves each in well under a second, but never two at once).
import { useCallback, useEffect, useState } from 'react'
import * as client from '../api/client'
import { ApiError } from '../api/client'
import type { DecisionReview, HandAnalysis } from '../api/types'

/** The parts of the API client the hook uses (injectable for tests). */
export type AnalysisApi = Pick<typeof client, 'getPlayAnalysis' | 'postPlayDecision'>

export interface AnalysisProgress {
  /** decisions already stored */
  done: number
  total: number
}

export interface HandAnalysisState {
  /** What is stored so far (a decision is `null` until it has been graded); null before the first load. */
  analysis: HandAnalysis | null
  progress: AnalysisProgress
  error: string | null
  /** A retry was asked for and nothing has come back yet. */
  retrying: boolean
  /** Continues from the first decision that is not stored. */
  retry: () => void
}

interface Loaded {
  handId: number
  analysis: HandAnalysis | null
  error: string | null
}

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return "Can't reach the server. Check it is running, then retry."
    return error.message
  }
  return error instanceof Error ? error.message : 'Something went wrong'
}

/**
 * Loads the analysis of `handId`, then posts each decision that is not stored, strictly one at a
 * time and in index order. A new `handId` or an unmount stops the loop and drops what is late.
 */
export function useHandAnalysis(handId: number, api: AnalysisApi = client): HandAnalysisState {
  const [loaded, setLoaded] = useState<Loaded>({ handId, analysis: null, error: null })
  const [attempt, setAttempt] = useState(0)
  const [retrying, setRetrying] = useState(false)

  useEffect(() => {
    let live = true
    // a retry shows "Retrying…" until it has stored a decision, finished or failed
    const show = (analysis: HandAnalysis | null, error: string | null, settled = true) => {
      if (!live) return
      setLoaded({ handId, analysis, error })
      if (settled) setRetrying(false)
    }
    const run = async () => {
      let analysis: HandAnalysis | null = null
      try {
        analysis = await api.getPlayAnalysis(handId)
        if (!live) return
        show(analysis, null, false)
        let posted = false
        for (let n = 0; n < analysis.decisions.length; n++) {
          if (analysis.decisions[n] !== null) continue
          const review = await api.postPlayDecision(handId, n)
          if (!live) return
          posted = true
          const decisions: (DecisionReview | null)[] = [...analysis.decisions]
          decisions[n] = review
          analysis = { ...analysis, decisions }
          show(analysis, null)
        }
        // the server's summary (and its note on the model) once everything is stored
        if (posted) show(await api.getPlayAnalysis(handId), null)
        else if (live) setRetrying(false)
      } catch (error) {
        show(analysis, message(error))
      }
    }
    void run()
    return () => {
      live = false
    }
  }, [handId, api, attempt])

  const retry = useCallback(() => {
    setRetrying(true)
    setAttempt((a) => a + 1)
  }, [])

  // a result for another hand is not this hand's (the render before the new load reports in)
  const mine = loaded.handId === handId ? loaded : null
  const analysis = mine?.analysis ?? null
  const decisions = analysis?.decisions ?? []
  return {
    analysis,
    progress: { done: decisions.filter((d) => d !== null).length, total: decisions.length },
    error: mine?.error ?? null,
    retrying,
    retry,
  }
}
