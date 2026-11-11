import { useEffect, useRef, useState } from 'react'
import { currentPuzzle, health } from '../api/client'

type Status =
  | { kind: 'loading' }
  | { kind: 'ready'; version: string; puzzleId: number | null }
  | { kind: 'error'; message: string }

/** Placeholder shell: proves the API connection until the table screen lands. */
export function App() {
  const [status, setStatus] = useState<Status>({ kind: 'loading' })
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    Promise.all([health(), currentPuzzle()])
      .then(([h, puzzle]) =>
        setStatus({ kind: 'ready', version: h.version, puzzleId: puzzle?.id ?? null }),
      )
      .catch((e: unknown) =>
        setStatus({ kind: 'error', message: e instanceof Error ? e.message : 'request failed' }),
      )
  }, [])

  return (
    <main style={{ padding: 'var(--space-6)' }}>
      <h1>Poker Puzzle Trainer</h1>
      {status.kind === 'loading' && <p>Connecting…</p>}
      {status.kind === 'error' && <p role="alert">Cannot reach the API: {status.message}</p>}
      {status.kind === 'ready' && (
        <p data-testid="status">
          API version {status.version}.{' '}
          {status.puzzleId === null ? 'No current puzzle.' : `Current puzzle: #${status.puzzleId}.`}
        </p>
      )}
    </main>
  )
}
