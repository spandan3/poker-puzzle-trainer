import type { KeyboardEvent } from 'react'
import { useId, useState } from 'react'
import type { DecisionData } from '../../lib/decision'
import { bbLabel, formatPct } from '../../lib/format'
import { optionLabel } from '../../lib/result'
import { CategoryTable } from './CategoryTable'
import { RangeGrid } from './RangeGrid'
import styles from './RangePanel.module.css'

export interface RangePanelProps {
  decision: DecisionData
}

interface ChoiceProps {
  legend: string
  items: { key: string; label: string }[]
  selected: number
  onSelect: (i: number) => void
}

function arrowStep(key: string): number {
  if (key === 'ArrowRight' || key === 'ArrowDown') return 1
  if (key === 'ArrowLeft' || key === 'ArrowUp') return -1
  return 0
}

/** A row of radio buttons (one group, arrow keys move the selection). */
function Choice({ legend, items, selected, onSelect }: ChoiceProps) {
  const labelId = useId()
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = arrowStep(e.key)
    if (step === 0) return
    e.preventDefault()
    const next = (selected + step + items.length) % items.length
    onSelect(next)
    e.currentTarget.querySelectorAll<HTMLButtonElement>('button')[next]?.focus()
  }
  return (
    <div className={styles.choice}>
      <span id={labelId} className={styles.legend}>
        {legend}
      </span>
      <div
        role="radiogroup"
        aria-labelledby={labelId}
        className={styles.buttons}
        onKeyDown={onKeyDown}
      >
        {items.map((item, i) => (
          <button
            key={item.key}
            type="button"
            role="radio"
            aria-checked={i === selected}
            tabIndex={i === selected ? 0 : -1}
            className={styles.button}
            onClick={() => onSelect(i)}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  )
}

/** Villain's range as it narrows, where it continues, and how Hero's hand fares against it. */
export function RangePanel({ decision }: RangePanelProps) {
  const { rangeSteps, options, categories, grade } = decision
  const stepsId = useId()
  const contId = useId()
  const catsId = useId()
  const [stepPick, setStepPick] = useState<number | null>(null)
  const stepIndex = stepPick ?? rangeSteps.length - 1
  const step = rangeSteps[stepIndex]

  const withGrid = options.flatMap((o, index) => (o.continue_grid ? [{ o, index }] : []))
  const defaultOption = (
    withGrid.find((x) => x.o.is_best) ??
    withGrid.find((x) => x.o.is_chosen) ??
    withGrid[0]
  )?.index
  const [optionPick, setOptionPick] = useState<number | null>(null)
  const shown = withGrid.find((x) => x.index === (optionPick ?? defaultOption))
  const optionName = (o: (typeof options)[number]) =>
    o.is_chosen ? decision.chosenLabel : optionLabel(o.label)

  const weighted = step ? step.combos.reduce((sum, [, w]) => sum + w, 0) : 0
  const equity = `your equity is ${formatPct(grade.equity)}.`
  const headline =
    grade.ahead_now === null
      ? `Your equity against this range is ${formatPct(grade.equity)}.`
      : `You're ahead of ${formatPct(grade.ahead_now)} of this range; ${equity}`

  return (
    <div className={styles.panel}>
      <p className={styles.headline}>{headline}</p>
      <div className={styles.views}>
        {step && (
          <section className={styles.view} aria-labelledby={stepsId}>
            <h3 id={stepsId} className={styles.heading}>
              Villain&apos;s range, step by step
            </h3>
            <Choice
              legend="Step"
              items={rangeSteps.map((s, i) => ({
                key: `${i}-${s.label}`,
                label: bbLabel(s.label),
              }))}
              selected={stepIndex}
              onSelect={setStepPick}
            />
            <RangeGrid grid={step.grid} label={bbLabel(step.label)} />
            <p className={styles.size}>
              {step.combos.length} combos, about {Number(weighted.toFixed(1))} weighted
            </p>
          </section>
        )}
        {shown?.o.continue_grid && (
          <section className={styles.view} aria-labelledby={contId}>
            <h3 id={contId} className={styles.heading}>
              Where Villain continues
            </h3>
            <Choice
              legend="Continues vs"
              items={withGrid.map(({ o, index }) => ({ key: String(index), label: optionName(o) }))}
              selected={withGrid.indexOf(shown)}
              onSelect={(i) => setOptionPick(withGrid[i]?.index ?? null)}
            />
            <RangeGrid grid={shown.o.continue_grid} label={`Continues vs ${optionName(shown.o)}`} />
            {shown.o.fold_freq !== null && (
              <p className={styles.size}>Folds: {formatPct(shown.o.fold_freq)}</p>
            )}
          </section>
        )}
      </div>
      {categories && (
        <section className={styles.cats} aria-labelledby={catsId}>
          <h3 id={catsId} className={styles.heading}>
            Hero vs range
          </h3>
          <div className={styles.scroll}>
            <CategoryTable
              categories={categories}
              hero={{ ahead: grade.ahead_now, equity: grade.equity }}
            />
          </div>
        </section>
      )}
    </div>
  )
}
