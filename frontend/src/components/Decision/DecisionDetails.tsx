import type { KeyboardEvent, ReactNode } from 'react'
import { forwardRef, useId, useImperativeHandle, useRef, useState } from 'react'
import type { DecisionData } from '../../lib/decision'
import { MathsPanel } from './MathsPanel'
import { OptionsTable } from './OptionsTable'
import { RangePanel } from './RangePanel'
import styles from './DecisionDetails.module.css'

const TAB_KEY = 'ppt.resultTab.v2'

type TabId = 'why' | 'options' | 'maths' | 'range' | 'hand'

const TAB_LABELS: Record<TabId, string> = {
  why: 'Why',
  options: 'Options',
  maths: 'Maths',
  range: 'Range',
  hand: 'Hand',
}

export interface DecisionDetailsProps {
  decision: DecisionData
  /** the Why tab's content (the plain-English explanation); no Why tab without it */
  whyTab?: ReactNode
  /** the Hand tab's content (puzzle-specific); no Hand tab without it */
  handTab?: ReactNode
}

export interface DecisionDetailsHandle {
  /** scroll the region into view and focus the selected tab */
  reveal: () => void
}

function readTab(): string | null {
  try {
    return window.localStorage.getItem(TAB_KEY)
  } catch {
    return null
  }
}

function writeTab(tab: TabId): void {
  try {
    window.localStorage.setItem(TAB_KEY, tab)
  } catch {
    // storage blocked: the choice lasts for this page only
  }
}

/** (Why,) Options, Maths, Range and (when given) Hand, as WAI-ARIA tabs. Why opens first when given. */
export const DecisionDetails = forwardRef<DecisionDetailsHandle, DecisionDetailsProps>(
  function DecisionDetails({ decision, whyTab, handTab }, handleRef) {
    const baseId = useId()
    const tabs: TabId[] = [
      ...(whyTab === undefined ? [] : (['why'] as const)),
      'options',
      'maths',
      'range',
      ...(handTab === undefined ? [] : (['hand'] as const)),
    ]
    const [stored, setStored] = useState(readTab)
    const selected: TabId = tabs.find((t) => t === stored) ?? tabs[0]!
    const rootRef = useRef<HTMLElement>(null)
    const tabRefs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({})

    const select = (tab: TabId, focus = false) => {
      setStored(tab)
      writeTab(tab)
      if (focus) tabRefs.current[tab]?.focus()
    }

    useImperativeHandle(handleRef, () => ({
      reveal: () => {
        const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
        rootRef.current?.scrollIntoView?.({
          block: 'start',
          behavior: reduced ? 'instant' : 'smooth',
        })
        tabRefs.current[selected]?.focus({ preventScroll: true })
      },
    }))

    const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
      const at = tabs.indexOf(selected)
      let next: number
      if (e.key === 'ArrowRight') next = (at + 1) % tabs.length
      else if (e.key === 'ArrowLeft') next = (at - 1 + tabs.length) % tabs.length
      else if (e.key === 'Home') next = 0
      else if (e.key === 'End') next = tabs.length - 1
      else return
      e.preventDefault()
      select(tabs[next]!, true)
    }

    const panel = (tab: TabId): ReactNode => {
      switch (tab) {
        case 'why':
          return whyTab
        case 'options':
          return <OptionsTable decision={decision} />
        case 'maths':
          return <MathsPanel decision={decision} />
        case 'range':
          return <RangePanel decision={decision} />
        case 'hand':
          return handTab
      }
    }

    return (
      <section ref={rootRef} className={styles.details} aria-label="Details">
        <h2 className={styles.srOnly}>Details</h2>
        <div role="tablist" aria-label="Details" className={styles.tabs} onKeyDown={onKeyDown}>
          {tabs.map((tab) => (
            <button
              key={tab}
              ref={(el) => {
                tabRefs.current[tab] = el
              }}
              type="button"
              role="tab"
              id={`${baseId}-tab-${tab}`}
              aria-selected={tab === selected}
              aria-controls={`${baseId}-panel-${tab}`}
              tabIndex={tab === selected ? 0 : -1}
              className={styles.tab}
              onClick={() => select(tab)}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </div>
        {tabs.map((tab) => (
          <div
            key={tab}
            role="tabpanel"
            id={`${baseId}-panel-${tab}`}
            aria-labelledby={`${baseId}-tab-${tab}`}
            hidden={tab !== selected}
            tabIndex={tab === selected ? 0 : undefined}
            className={styles.panel}
          >
            {tab === selected && panel(tab)}
          </div>
        ))}
      </section>
    )
  },
)
