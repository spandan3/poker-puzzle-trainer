import type { CSSProperties } from 'react'
import type { PlaySessionView } from '../../api/types'
import type { PlayFlow } from '../../app/usePlayFlow'
import { PlayPage } from '../../components/Play/PlayPage'
import { playSessionFixture, playSessionsFixture, settingsFixture } from '../../test/fixture'
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
      flow={flow(session, shownCount)}
      settings={settingsFixture()}
      shortcutsOn={false}
      onAnalyse={() => undefined}
    />
  )
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
    </>
  ),
}

export default entry
