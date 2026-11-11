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
export type SettingsView = Schemas['SettingsView']
export type SettingsPatch = Schemas['SettingsPatch']
export type Health = Schemas['Health']

export type StreetName = ActionLogEntry['street']
export type ActionKindName = ActionLogEntry['kind']
export type Intent = NonNullable<AttemptIn['intent']>
