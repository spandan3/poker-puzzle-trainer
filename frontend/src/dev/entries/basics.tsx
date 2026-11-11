import type { GalleryEntry } from '../Gallery'
import { formatBb } from '../../lib/format'
import { cardName, parseCard, rankGlyph, suitGlyph } from '../../lib/cards'
import { fixtureNames } from '../../test/fixture'

const SWATCHES = [
  '--color-bg',
  '--color-panel',
  '--color-felt',
  '--color-accent',
  '--color-danger',
  '--color-warning',
  '--color-info',
  '--color-card-face',
]

const entry: GalleryEntry = {
  title: 'Basics',
  render: () => (
    <div style={{ display: 'grid', gap: 'var(--space-5)' }}>
      <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
        {SWATCHES.map((name) => (
          <div key={name} style={{ textAlign: 'center', fontSize: 'var(--text-xs)' }}>
            <div
              style={{
                width: 72,
                height: 48,
                background: `var(${name})`,
                border: '1px solid var(--color-panel-border)',
                borderRadius: 'var(--radius-sm)',
              }}
            />
            {name.replace('--color-', '')}
          </div>
        ))}
      </div>
      <p>Chips to bb: {[1, 5, 13, 200].map(formatBb).join(' · ')}</p>
      <p>
        {['Th', 'As', 'Kd', 'Qc'].map((c) => {
          const { rank, suit } = parseCard(c)
          return (
            <span key={c} title={cardName(c)} style={{ marginRight: 'var(--space-4)' }}>
              {rankGlyph(rank)}
              {suitGlyph(suit)}
            </span>
          )
        })}
      </p>
      <p>Fixtures available: {fixtureNames().join(', ')}</p>
    </div>
  ),
}

export default entry
