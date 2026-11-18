import type { CSSProperties } from 'react'
import type { PlaySessionView } from '../../api/types'
import type { PlayFlow } from '../../app/usePlayFlow'
import { PlayPage } from '../../components/Play/PlayPage'
import { HandAnalysis } from '../../components/Play/HandAnalysis'
import { SessionHands } from '../../components/Play/SessionHands'
import {
  explanationLlmFixture,
  playHandAnalysisFixture,
  playHandsFixture,
  playSessionFixture,
  playSessionsFixture,
  settingsFixture,
} from '../../test/fixture'
import type { GalleryEntry } from '../Gallery'

const caption: CSSProperties = {
  margin: 'var(--space-5) 0 var(--space-2)',
  color: 'var(--color-text-muted)',
  fontSize: 'var(--text-sm)',
}

function flow(session: PlaySessionView | null, shownCount?: number): PlayFlow {
  const total = session?.hand?.table.history.length ?? 0
  const shown = shownCount ?? total
  return {
    state: session ? { kind: 'playing' } : { kind: 'idle' },
    session,
    past: playSessionsFixture(),
    shownCount: shown,
    revealing: shown < total,
    busy: false,
    start: () => undefined,
    act: () => undefined,
    nextHand: () => undefined,
    end: () => undefined,
    retry: () => undefined,
  }
}

function Page({ session, shownCount }: { session: PlaySessionView | null; shownCount?: number }) {
  return (
    <PlayPage
      as="div"
      flow={flow(session, shownCount)}
      settings={settingsFixture()}
      shortcutsOn={false}
    />
  )
}

const analysisApi = {
  getPlayAnalysis: async () => playHandAnalysisFixture(),
  postPlayDecision: async (_handId: number, n: number) => playHandAnalysisFixture().decisions[n]!,
  getPlayExplanation: async () => explanationLlmFixture(),
  listPlayHands: async () => playHandsFixture(),
}

const entry: GalleryEntry = {
  title: 'Play page',
  render: () => (
    <>
      <p style={caption}>Hero to act</p>
      <Page session={playSessionFixture('hero_to_act')} />
      <p style={caption}>The bot&apos;s actions being revealed (1 of 8 shown)</p>
      <Page session={playSessionFixture('hand_over_showdown')} shownCount={1} />
      <p style={caption}>Hand over by showdown</p>
      <Page session={playSessionFixture('hand_over_showdown')} />
      <p style={caption}>Hand over by fold</p>
      <Page session={playSessionFixture('hand_over_fold')} />
      <p style={caption}>No open session</p>
      <Page session={null} />
      <p style={caption}>Hand analysis (a stored showdown hand)</p>
      <HandAnalysis
        handId={playHandAnalysisFixture().hand_id}
        api={analysisApi}
        settings={settingsFixture()}
        onClose={() => undefined}
      />
      <p style={caption}>Session hands</p>
      <SessionHands sessionId={1} api={analysisApi} onOpen={() => undefined} />
    </>
  ),
}

export default entry
