import { useState } from 'react'
import type { AttemptIn, PuzzleView } from '../../api/types'
import { AnswerPanel } from '../../components/AnswerPanel/AnswerPanel'
import { ShortcutsOverlay } from '../../components/ShortcutsOverlay/ShortcutsOverlay'
import type { AnswerState } from '../../lib/answer'
import { formatBb, formatPct } from '../../lib/format'
import { puzzleFixture } from '../../test/fixture'
import type { GalleryEntry } from '../Gallery'

interface Case {
  id: string
  title: string
  fixture: string
  initial?: Partial<AnswerState>
  error?: string
  customDisabledReason?: string
}

const CASES: Case[] = [
  {
    id: 'flop-unopened',
    title: 'Unopened flop, a size selected',
    fixture: 'flop_unopened',
    initial: { equity: '42', rangeRead: '58', rangeSkipped: false, action: 'bet', size: 3 },
  },
  {
    id: 'facing-bet',
    title: 'Facing a bet (flop raise), custom size',
    fixture: 'facing_postflop_raise',
    initial: {
      equity: '38',
      action: 'raise',
      size: 'custom',
      custom: '12.5',
      intent: 'semi_bluff',
    },
  },
  { id: 'btn-first-in', title: 'Pre-flop, BTN first in (fresh)', fixture: 'preflop_btn_first_in' },
  {
    id: 'facing-all-in',
    title: 'Facing an all-in: fold or call',
    fixture: 'facing_all_in',
    initial: { equity: '31', action: 'call' },
  },
  {
    id: 'river',
    title: 'River: no range read',
    fixture: 'river',
    initial: { equity: '64', action: 'bet', size: 2, intent: 'value' },
  },
  {
    id: 'errors',
    title: 'Custom size error and a server error',
    fixture: 'custom_allowed',
    initial: { equity: '55', action: 'bet', size: 'custom', custom: '2.3' },
    error:
      'equity_guess: Input should be less than or equal to 1; give exactly one of option or custom_to',
  },
  {
    id: 'custom-disabled',
    title: 'After a 409: custom sizes disabled',
    fixture: 'custom_allowed',
    initial: { equity: '55', action: 'bet', size: 1 },
    customDisabledReason:
      'The Villain model changed since this puzzle was made; pick a listed size',
  },
]

function context(view: PuzzleView): string {
  const parts = [
    `${view.street} · ${view.hero_position} vs ${view.villain_position}`,
    `pot ${formatBb(view.pot)}`,
  ]
  if (view.to_call > 0) parts.push(`to call ${formatBb(view.to_call)}`)
  if (view.pot_odds !== null) parts.push(`pot odds ${formatPct(view.pot_odds)}`)
  return parts.join(' · ')
}

function AnswerGallery() {
  // one panel at a time takes the keyboard: the one last clicked or focused
  const [active, setActive] = useState(CASES[0]?.id ?? '')
  const [sent, setSent] = useState<Record<string, AttemptIn>>({})
  const [overlay, setOverlay] = useState(false)

  return (
    <div style={{ display: 'grid', gap: 'var(--space-6)' }}>
      <p style={{ margin: 0, color: 'var(--color-text-muted)' }}>
        Click a panel to give it the keyboard.{' '}
        <button type="button" onClick={() => setOverlay(true)}>
          Show shortcuts overlay
        </button>
      </p>
      {CASES.map((c) => {
        const view = puzzleFixture(c.fixture)
        return (
          <div
            key={c.id}
            data-gallery-case={c.id}
            onPointerDownCapture={() => setActive(c.id)}
            onFocusCapture={() => setActive(c.id)}
            style={{ display: 'grid', gap: 'var(--space-2)', maxWidth: 1040 }}
          >
            <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'baseline' }}>
              <h3 style={{ margin: 0, fontSize: 'var(--text-md)' }}>{c.title}</h3>
              <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>
                {context(view)}
                {active === c.id ? ' · keyboard here' : ''}
              </span>
            </div>
            <AnswerPanel
              view={view}
              busy={false}
              error={c.error ?? null}
              customDisabledReason={c.customDisabledReason ?? null}
              shortcutsOn={active === c.id}
              initial={c.initial}
              onSubmit={(body) => setSent((s) => ({ ...s, [c.id]: body }))}
            />
            {sent[c.id] && (
              <code style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-xs)' }}>
                POST body: {JSON.stringify(sent[c.id])}
              </code>
            )}
          </div>
        )
      })}
      <ShortcutsOverlay open={overlay} onClose={() => setOverlay(false)} />
    </div>
  )
}

const entry: GalleryEntry = {
  title: 'Answer panel',
  render: () => <AnswerGallery />,
}

export default entry
