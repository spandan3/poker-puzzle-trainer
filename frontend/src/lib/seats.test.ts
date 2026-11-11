import { describe, expect, it } from 'vitest'
import { puzzleFixture } from '../test/fixture'
import { seatsFromView } from './seats'

describe('seatsFromView', () => {
  it('puts Hero at the bottom and Villain at the top', () => {
    const seats = seatsFromView(puzzleFixture('preflop_bb_facing_open'), { showProfile: true })
    expect(seats.map((s) => [s.slot, s.name, s.isHero])).toEqual([
      ['bottom', 'Hero', true],
      ['top', 'Villain', false],
    ])
  })

  it('reads positions, stacks and bets by seat (Hero in seat 0)', () => {
    const [hero, villain] = seatsFromView(puzzleFixture('preflop_bb_facing_open'), {
      showProfile: true,
    })
    expect(hero).toMatchObject({ position: 'BB', stackChips: 198, betChips: 2, isButton: false })
    expect(villain).toMatchObject({ position: 'BTN', stackChips: 195, betChips: 5, isButton: true })
  })

  it('reads positions, stacks and bets by seat (Hero in seat 1)', () => {
    const [hero, villain] = seatsFromView(puzzleFixture('preflop_facing_3bet'), {
      showProfile: true,
    })
    expect(hero).toMatchObject({ position: 'BTN', stackChips: 195, betChips: 5, isButton: true })
    expect(villain).toMatchObject({
      position: 'BB',
      stackChips: 185,
      betChips: 15,
      isButton: false,
    })
  })

  it("shows Hero's cards and keeps Villain's face down with no identity", () => {
    const view = puzzleFixture('preflop_bb_facing_open')
    const [hero, villain] = seatsFromView(view, { showProfile: true })
    expect(hero).toMatchObject({ cards: view.hero_cards, faceDown: false })
    expect(villain).toMatchObject({ cards: [null, null], faceDown: true })
  })

  it("reveals Villain's cards when given", () => {
    const [, villain] = seatsFromView(puzzleFixture('river'), {
      showProfile: true,
      villainCards: ['As', 'Kd'],
    })
    expect(villain).toMatchObject({ cards: ['As', 'Kd'], faceDown: false })
  })

  it("carries Villain's profile and hides it when the setting is off", () => {
    const view = puzzleFixture('preflop_facing_3bet')
    const [hero, shown] = seatsFromView(view, { showProfile: true })
    expect(shown?.profile).toEqual({
      label: view.villain_profile.label,
      description: view.villain_profile.description,
    })
    expect(shown?.showProfile).toBe(true)
    expect(hero?.profile).toBeUndefined()
    expect(hero?.showProfile).toBe(false)
    const [, hidden] = seatsFromView(view, { showProfile: false })
    expect(hidden?.showProfile).toBe(false)
  })

  it('keeps an all-in stack at zero', () => {
    const [hero, villain] = seatsFromView(puzzleFixture('facing_all_in'), { showProfile: true })
    expect(hero).toMatchObject({ stackChips: 84, betChips: 0 })
    expect(villain).toMatchObject({ stackChips: 0, betChips: 84 })
  })
})
