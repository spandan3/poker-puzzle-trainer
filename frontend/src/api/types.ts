import type { components } from './schema'

type Schemas = components['schemas']

export type PuzzleView = Schemas['PuzzleView']
export type OptionBrief = Schemas['OptionBrief']
export type ActionLogEntry = Schemas['ActionLogEntry']
export type CustomSizes = Schemas['CustomSizes']
export type ProfileInfo = Schemas['ProfileInfo']
export type NewPuzzleIn = Schemas['NewPuzzleIn']
export type AttemptIn = Schemas['AttemptIn']
export type AttemptResult = Schemas['AttemptResult']
export type OptionResult = Schemas['OptionResult']
export type SettingsView = Schemas['SettingsView']
export type SettingsPatch = Schemas['SettingsPatch']
export type Health = Schemas['Health']
export type StatsView = Schemas['StatsView']
export type TrendPoint = Schemas['TrendPoint']
export type BreakdownRow = Schemas['BreakdownRow']
export type Leak = Schemas['Leak']
export type HistoryPage = Schemas['HistoryPage']
export type AttemptSummary = Schemas['AttemptSummary']
export type Explanation = Schemas['Explanation']
export type ExplanationSection = Schemas['ExplanationSection']

export type TableView = Schemas['TableView']
export type TableFrame = Schemas['TableFrame']
export type PlayHandView = Schemas['PlayHandView']
export type PlaySessionView = Schemas['PlaySessionView']
export type PlaySessionSummary = Schemas['PlaySessionSummary']
export type PlayHandSummary = Schemas['PlayHandSummary']
export type PlayOutcome = Schemas['PlayOutcome']
export type PlayReveal = Schemas['PlayReveal']
export type PlayActionIn = Schemas['PlayActionIn']
export type NextHandIn = Schemas['NextHandIn']
export type DecisionReview = Schemas['DecisionReview']
export type HandAnalysis = Schemas['HandAnalysis']

/** What Hero picks at a play decision: a listed option's index, or a custom size in chips. */
export type PlayActionChoice = { option: number } | { custom_to: number }

/**
 * What the answer panel needs: the table plus Hero's menu. A `PuzzleView` satisfies it; for a
 * played hand it is `{ ...hand.table, options: hand.options, custom: hand.custom }`.
 */
export type ActionView = TableView & {
  options: OptionBrief[]
  custom: CustomSizes
  id?: number
  attempts_so_far?: number
  range_read_asked?: boolean
}

export type StreetName = ActionLogEntry['street']
export type ActionKindName = ActionLogEntry['kind']
export type Intent = NonNullable<AttemptIn['intent']>
