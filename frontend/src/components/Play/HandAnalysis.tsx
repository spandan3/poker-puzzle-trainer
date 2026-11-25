import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import * as client from '../../api/client'
import type {
  DecisionReview,
  HandAnalysis as Analysis,
  SettingsView,
  TableView,
} from '../../api/types'
import type { AnalysisApi } from '../../app/useHandAnalysis'
import { useHandAnalysis } from '../../app/useHandAnalysis'
import type { LlmSettings } from '../../app/useExplanation'
import { useExplanation } from '../../app/useExplanation'
import { decisionFromReview } from '../../lib/decision'
import { formatEvBb } from '../../lib/format'
import { STREET_LABELS } from '../../lib/history'
import type { Page } from '../../lib/page'
import { revealShowdownLine } from '../../lib/play'
import { gradeLine, judgedNote, reviewChosenLabel, VERDICT_LABELS } from '../../lib/result'
import { Badge, Button, Panel } from '../ui'
import type { BadgeTone } from '../ui'
import { Card } from '../Card/Card'
import { DecisionDetails } from '../Decision/DecisionDetails'
import { ExplanationPanel } from '../Explanation/ExplanationPanel'
import hand from '../HandReveal/HandReveal.module.css'
import styles from './HandAnalysis.module.css'

/** The parts of the API client the analysis view uses (injectable for tests). */
export type HandAnalysisApi = AnalysisApi & Pick<typeof client, 'getPlayExplanation'>

export interface HandAnalysisProps {
  handId: number
  api?: HandAnalysisApi
  /** the settings' LLM fields (whether the Why tab asks for a reworded explanation) and show_range (the Range tab) */
  settings: (LlmSettings & Pick<SettingsView, 'show_range'>) | null
  /** the Why tab's "Settings" link */
  onNavigate?: (page: Page) => void
  onClose: () => void
  /**
   * The table at the selected decision (null while loading or when none is stored): the page
   * shows it in the Action panel, so the panel follows the hand being analysed.
   */
  onView?: (view: TableView | null) => void
}

const TONES: Record<string, BadgeTone> = {
  best: 'best',
  fine: 'fine',
  mistake: 'mistake',
  blunder: 'blunder',
}

type GradedReview = DecisionReview & { status: 'graded' }

const isGraded = (d: DecisionReview): d is GradedReview => d.status === 'graded' && d.grade !== null

/** "Decision 2 · Flop": the heading of a step's details. */
function stepHeading(review: DecisionReview): string {
  const street = review.view ? ` · ${STREET_LABELS[review.view.street]}` : ''
  return `Decision ${review.index + 1}${street}`
}

function stepTitle(review: DecisionReview): string {
  const street = review.view ? STREET_LABELS[review.view.street] : `Decision ${review.index + 1}`
  return review.chosen_label ? `${street} · ${reviewChosenLabel(review.chosen_label)}` : street
}

/**
 * The analysis of one finished hand: loads what is stored, grades what is missing (showing the
 * progress), then the summary, the steps and, for the step picked, the details tabs.
 */
export function HandAnalysis({
  handId,
  api = client,
  settings,
  onNavigate,
  onClose,
  onView,
}: HandAnalysisProps) {
  const { analysis, progress, error, retrying, retry } = useHandAnalysis(handId, api)
  const rootRef = useRef<HTMLDivElement>(null)
  useEffect(() => rootRef.current?.focus({ preventScroll: true }), [handId])

  const complete = analysis !== null && progress.done === progress.total
  const finished =
    !retrying && error === null && complete && analysis !== null && analysis.decisions.length > 0
  const reviews = finished ? analysis.decisions.filter((d): d is DecisionReview => d !== null) : []
  const summary = finished ? analysis.summary : null
  const [picked, setPicked] = useState<number | null>(null)
  const selected = picked ?? summary?.worst_index ?? 0
  const review = reviews[selected] ?? reviews[0] ?? null
  const view = review?.view ?? null
  // the Action panel follows the step on show
  useEffect(() => {
    onView?.(view)
  }, [view, onView])

  let body: ReactNode
  if (retrying) {
    body = (
      <p className={styles.status} role="status">
        Retrying…
      </p>
    )
  } else if (error !== null) {
    body = (
      <div className={styles.status} role="alert">
        <span>{error}</span>
        <Button size="sm" onClick={retry}>
          Retry
        </Button>
        {analysis !== null && progress.total > 0 && (
          <span className={styles.muted}>
            {progress.done} of {progress.total} decisions analysed so far.
          </span>
        )}
      </div>
    )
  } else if (analysis === null) {
    body = (
      <p className={styles.status} role="status">
        Loading the analysis…
      </p>
    )
  } else if (!complete) {
    body = (
      <p className={styles.status} role="status">
        Analysing decision {progress.done + 1} of {progress.total}…
      </p>
    )
  } else if (analysis.decisions.length === 0) {
    body = <p className={styles.status}>You made no decision in this hand.</p>
  } else {
    body = <Summary analysis={analysis} reviews={reviews} selected={selected} onPick={setPicked} />
  }

  return (
    <div ref={rootRef} tabIndex={-1} className={styles.root}>
      <AnalysisPanel onClose={onClose}>{body}</AnalysisPanel>
      {finished && review && (
        <StepDetails
          key={review.index}
          handId={handId}
          review={review}
          analysis={analysis}
          api={api}
          settings={settings}
          onNavigate={onNavigate}
        />
      )}
    </div>
  )
}

/** The header panel: the title, Close analysis and what goes under them. */
function AnalysisPanel({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  return (
    <Panel
      title="Hand analysis"
      headingLevel={2}
      actions={<Button onClick={onClose}>Close analysis</Button>}
    >
      <div className={styles.panelBody}>{children}</div>
    </Panel>
  )
}

/** The summary and the step list: what sits in the header panel once everything is graded. */
function Summary({
  analysis,
  reviews,
  selected,
  onPick,
}: {
  analysis: Analysis
  reviews: DecisionReview[]
  selected: number
  onPick: (index: number) => void
}) {
  const { summary } = analysis
  return (
    <>
      {analysis.model_changed && (
        <p className={styles.note} role="note">
          Villain model has changed since this hand
        </p>
      )}
      <section className={styles.summary} aria-label="Summary">
        <p className={styles.total}>
          Total EV lost: <strong>{formatEvBb(summary?.ev_loss_bb ?? 0)}</strong>
        </p>
        <p className={styles.muted}>
          {summary?.worst_index != null && reviews[summary.worst_index]
            ? `Worst decision: ${stepTitle(reviews[summary.worst_index]!)}`
            : reviews.some(isGraded)
              ? 'No decision lost EV.'
              : 'No decision could be graded.'}
        </p>
        <p className={styles.muted}>
          {/* a fold ends the hand: Hero's last decision */}
          {judgedNote(analysis.judged_on_range_note, reviews.at(-1)?.chosen_label === 'fold')}
        </p>
      </section>

      <ol className={styles.steps} aria-label="Decisions">
        {reviews.map((r, i) => {
          const graded = isGraded(r)
          return (
            <li key={r.index} className={styles.step}>
              <button
                type="button"
                className={styles.stepButton}
                aria-current={i === selected ? 'step' : undefined}
                data-verdict={graded ? r.grade!.verdict : 'none'}
                onClick={() => onPick(i)}
              >
                <span className={styles.stepTitle}>{stepTitle(r)}</span>
                {graded ? (
                  <>
                    <Badge tone={TONES[r.grade!.verdict] ?? 'neutral'}>
                      {VERDICT_LABELS[r.grade!.verdict]}
                    </Badge>
                    <span className={styles.loss}>{formatEvBb(r.grade!.ev_loss_bb)} lost</span>
                  </>
                ) : (
                  <span className={styles.loss}>Not graded: {r.reason}</span>
                )}
                {i === summary?.worst_index && <span className={styles.worst}>Most EV lost</span>}
              </button>
            </li>
          )
        })}
      </ol>
    </>
  )
}

function StepDetails({
  handId,
  review,
  analysis,
  api,
  settings,
  onNavigate,
}: {
  handId: number
  review: DecisionReview
  analysis: Analysis
  api: HandAnalysisApi
  settings: (LlmSettings & Pick<SettingsView, 'show_range'>) | null
  onNavigate?: (page: Page) => void
}) {
  const graded = isGraded(review)
  const explained = useExplanation(
    graded ? `play:${handId}:${review.index}` : null,
    review.explanation,
    (signal) => api.getPlayExplanation(handId, review.index, signal),
    settings,
  )
  // a step that was not graded has its reason in the list and nothing more to show
  if (!graded) return null
  const decision = decisionFromReview(review)
  const { grade } = decision
  return (
    <div className={styles.details}>
      <div className={styles.stepHead}>
        <p className={styles.stepName}>{stepHeading(review)}</p>
        <p className={styles.gradeLine}>{gradeLine(decision.chosenLabel, grade)}</p>
      </div>
      <DecisionDetails
        decision={decision}
        whyTab={
          <ExplanationPanel
            explanation={explained?.explanation ?? review.explanation!}
            pendingModel={explained?.pendingModel}
            requestFailed={explained?.requestFailed}
            llmStatus={settings?.llm_status}
            llmDetail={settings?.llm_detail}
            onNavigate={onNavigate}
          />
        }
        handTab={<PlayHandTab analysis={analysis} review={review} />}
        showRange={settings?.show_range ?? false}
      />
    </div>
  )
}

/** The Hand tab: the bot's cards and profile, the board as dealt, the showdown, the simplifications. */
function PlayHandTab({ analysis, review }: { analysis: Analysis; review: DecisionReview }) {
  const { reveal } = analysis
  return (
    <div className={hand.hand}>
      <div className={hand.cols}>
        <section className={hand.block}>
          <h3 className={hand.heading}>Villain</h3>
          <div className={hand.cards} role="group" aria-label="Villain's hand">
            {reveal.villain_cards.map((c) => (
              <Card key={c} card={c} size="md" />
            ))}
          </div>
          <p className={hand.profileLine}>
            <span className={hand.profile}>{reveal.profile.label}</span>{' '}
            <span className={hand.muted}>{reveal.profile.description}</span>
          </p>
        </section>
        <section className={hand.block}>
          {reveal.board.length > 0 ? (
            <>
              <h3 className={hand.heading}>Board</h3>
              <div className={hand.cards} role="group" aria-label="Board">
                {reveal.board.map((c) => (
                  <Card key={c} card={c} size="md" />
                ))}
              </div>
            </>
          ) : (
            <p className={hand.muted}>No board cards were dealt.</p>
          )}
          <p className={hand.showdown}>{revealShowdownLine(reveal)}</p>
        </section>
      </div>
      {review.simplifications.length > 0 && (
        <section className={hand.block}>
          <h3 className={hand.heading}>Simplifications</h3>
          <ul className={hand.list} aria-label="Simplifications">
            {review.simplifications.map((s) => (
              <li key={s.code}>{s.text}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
