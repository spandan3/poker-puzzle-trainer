import { useState } from 'react'
import type { GalleryEntry } from '../Gallery'
import { Badge, Button, ConfirmDialog, Panel, Select, Toggle } from '../../components/ui'
import type { BadgeTone } from '../../components/ui'

const TONES: BadgeTone[] = ['best', 'fine', 'mistake', 'blunder', 'neutral', 'profile']

const row = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 'var(--space-3)',
  alignItems: 'center',
} as const

function UiGallery() {
  const [street, setStreet] = useState('')
  const [potOdds, setPotOdds] = useState(true)
  const [profile, setProfile] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [result, setResult] = useState('none yet')
  return (
    <div style={{ display: 'grid', gap: 'var(--space-5)', maxWidth: '44rem' }}>
      <Panel title="Buttons">
        <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
          {(['md', 'sm'] as const).map((size) => (
            <div key={size} style={row}>
              <Button variant="primary" size={size}>
                Primary
              </Button>
              <Button variant="primary" size={size} kbd="N">
                New puzzle
              </Button>
              <Button variant="secondary" size={size}>
                Secondary
              </Button>
              <Button variant="ghost" size={size}>
                Ghost
              </Button>
              <Button variant="secondary" size={size} busy>
                Checking…
              </Button>
              <Button variant="secondary" size={size} disabled>
                Disabled
              </Button>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Select">
        <Select label="Street" value={street} onChange={setStreet}>
          <option value="">Any street</option>
          <option value="flop">Flop</option>
          <option value="turn">Turn</option>
          <option value="river">River</option>
        </Select>
        <div style={{ marginTop: 'var(--space-3)' }}>
          <Select label="Street (disabled)" value="" onChange={() => {}} disabled>
            <option value="">Any street</option>
          </Select>
        </div>
      </Panel>

      <Panel title="Badges">
        <div style={row}>
          {TONES.map((tone) => (
            <Badge key={tone} tone={tone}>
              {tone}
            </Badge>
          ))}
        </div>
      </Panel>

      <Panel title="Toggles">
        <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
          <Toggle label="Pot odds" on={potOdds} onChange={setPotOdds} />
          <Toggle
            label="Show profile"
            description="Shows the Villain's profile on the table."
            on={profile}
            onChange={setProfile}
          />
          <Toggle
            label="Shortcuts (on, with a description)"
            description="Single keys answer and move on."
            on
            onChange={() => {}}
          />
        </div>
      </Panel>

      <Panel title="Flush panel with actions" actions={<Button size="sm">Action</Button>} flush>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
          <tbody>
            <tr>
              <td style={{ padding: 'var(--space-2) var(--space-4)' }}>Row</td>
              <td style={{ padding: 'var(--space-2) var(--space-4)' }}>1.5 bb</td>
            </tr>
          </tbody>
        </table>
      </Panel>

      <Panel title="Confirm dialog">
        <div style={row}>
          <Button onClick={() => setConfirming(true)}>Open dialog</Button>
          <span>Last result: {result}</span>
        </div>
        {confirming && (
          <ConfirmDialog
            title="Leave this puzzle?"
            body="Your answer has not been submitted."
            confirmLabel="Leave"
            cancelLabel="Stay"
            onConfirm={() => {
              setResult('confirmed')
              setConfirming(false)
            }}
            onCancel={() => {
              setResult('cancelled')
              setConfirming(false)
            }}
          />
        )}
      </Panel>
    </div>
  )
}

const entry: GalleryEntry = {
  title: 'UI primitives',
  render: () => <UiGallery />,
}

export default entry
