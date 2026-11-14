import { describe, expect, it } from 'vitest'
import type { AttemptResult } from '../api/types'
import { attemptFixture, puzzleFixture } from '../test/fixture'
import { entryTexts } from './history'
import {
  answerEntry,
  chosenLabel,
  guessLines,
  optionLabel,
  heroFolded,
  showdownLine,
  verdictLine,
} from './result'

type Grade = AttemptResult['grade']

function withGrade(result: AttemptResult, grade: Partial<Grade>): AttemptResult {
  return { ...result, grade: { ...result.grade, ...grade } }
}

describe('optionLabel', () => {
  it.each([
    ['bet 33%', 'Bet 33%'],
    ['bet 100%', 'Bet pot'],
    ['raise 2.5x', 'Raise 2.5x'],
    ['all-in', 'All-in'],
    ['call', 'Call'],
    ['fold', 'Fold'],
  ])('%s -> %s', (label, shown) => expect(optionLabel(label)).toBe(shown))
})

describe('chosenLabel', () => {
  it('uses the option label', () => {
    expect(chosenLabel(attemptFixture('bet'))).toBe('Bet 33%')
  })

  it('rebuilds a custom size in bb (the server label is in chips)', () => {
    const r = attemptFixture('bet')
    const custom: AttemptResult = {
      ...r,
      answer: {
        ...r.answer,
        chosen_label: 'bet 13',
        custom_to: 13,
        option_index: null,
        action: { ...r.answer.action, to: 13 },
      },
    }
    expect(chosenLabel(custom)).toBe('Bet 6.5 bb')
    const raise: AttemptResult = {
      ...custom,
      answer: { ...custom.answer, action: { ...custom.answer.action, kind: 'raise' } },
    }
    expect(chosenLabel(raise)).toBe('Raise to 6.5 bb')
  })
})

describe('verdictLine', () => {
  const bet = attemptFixture('bet')

  it('the top play', () => {
    expect(verdictLine(bet)).toBe('You: Bet 33% · the top play')
  })

  it('a custom size that beats the listed best is the top play', () => {
    const custom = attemptFixture('custom')
    expect(custom.grade.ev_loss_bb).toBe(0)
    expect(verdictLine(custom)).toBe('You: Bet 1 bb · the top play')
  })

  it('close to the top play: names it, without the verdict word', () => {
    const r = withGrade(bet, { verdict: 'fine', ev_loss_bb: 0.1149, best_label: 'bet 75%' })
    expect(verdictLine(r)).toBe('You: Bet 33% · within 0.11 bb of the top play (Bet 75%)')
  })

  it('a mistake: "Top EV:" and the EV lost', () => {
    const fold = attemptFixture('fold')
    expect(fold.grade.verdict).toBe('mistake')
    expect(verdictLine(fold)).toBe('You: Fold · Top EV: Call · 2.26 bb lost')
    for (const word of ['Best', 'Fine', 'Mistake', 'Blunder']) {
      expect(verdictLine(fold)).not.toContain(word)
    }
  })
})

describe('guessLines', () => {
  it('equity, and the range read when it was asked', () => {
    const lines = guessLines(attemptFixture('bet'))
    expect(lines.map((l) => l.label)).toEqual(['Equity', 'Range read'])
    expect(lines[0]).toMatchObject({ guess: '45%', actual: '46.4%', score: 'great' })
  })

  it('no range read line when none was given', () => {
    const r = withGrade(attemptFixture('bet'), { range_read_guess: null, range_read_score: null })
    expect(guessLines(r).map((l) => l.label)).toEqual(['Equity'])
  })
})

describe('showdownLine', () => {
  it('names the winner', () => {
    expect(showdownLine(attemptFixture('bet'))).toBe('Hero wins: Pair vs Pair')
  })

  it('says there is no showdown after a fold', () => {
    expect(showdownLine(attemptFixture('fold'))).toBe("You folded, so there's no showdown.")
  })
})

describe('heroFolded', () => {
  it('is true for a fold on any street, false otherwise', () => {
    expect(heroFolded(attemptFixture('fold'))).toBe(true)
    expect(heroFolded(attemptFixture('fold_preflop'))).toBe(true)
    expect(heroFolded(attemptFixture('bet'))).toBe(false)
  })
})

describe('answerEntry', () => {
  it('renders like a history entry', () => {
    const view = puzzleFixture('flop_unopened')
    const entry = answerEntry(view, attemptFixture('bet'))
    expect(entry).toMatchObject({ actor: 'hero', kind: 'bet', to: 3, amount: 3, all_in: false })
    expect(entryTexts([entry])).toEqual(['bets 1.5 bb (30% pot)'])
  })

  it('a fold moves no chips', () => {
    const view = puzzleFixture('preflop_bb_facing_open')
    const fold = attemptFixture('fold')
    const entry = answerEntry(view, {
      ...fold,
      answer: { ...fold.answer, action: { ...fold.answer.action, street: view.street } },
    })
    expect(entry).toMatchObject({ kind: 'fold', amount: 0, all_in: false })
    expect(entryTexts([entry])).toEqual(['folds'])
  })
})
