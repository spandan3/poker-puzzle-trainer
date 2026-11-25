import { describe, expect, it } from 'vitest'
import { play5SessionFixture, playSessionFixture, puzzleFixture } from '../test/fixture'
import { seatsFromPlayTable, seatsFromView } from './seats'

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

describe('seatsFromView with a play table', () => {
  it('reads a played hand’s table', () => {
    const table = playSessionFixture('hero_to_act').hand!.table
    const seats = seatsFromView(table, { showProfile: true })
    expect(seats.map((s) => s.name)).toEqual(['Hero', 'Villain'])
    expect(seats[0]!.cards).toEqual(table.hero_cards)
    expect(seats[1]!.faceDown).toBe(true)
    expect(seats[1]!.profile?.label).toBe(table.villain_profile?.label)
  })
})

describe('seatsFromPlayTable', () => {
  const five = play5SessionFixture('hero_to_act').hand!
  const side = play5SessionFixture('side_pot').hand!

  it('puts Hero at the bottom and the bots clockwise from Hero', () => {
    const seats = seatsFromPlayTable(five.table, { showProfile: true })
    expect(seats.map((s) => [s.slot, s.name])).toEqual([
      ['bottom', 'You'],
      ['bottom-left', 'Bot 1'],
      ['top-left', 'Bot 2'],
      ['top-right', 'Bot 3'],
      ['bottom-right', 'Bot 4'],
    ])
  })

  it('puts the one bot of a heads-up play table at the top', () => {
    const view = playSessionFixture('hero_to_act').hand!.table
    const seats = seatsFromPlayTable(view, { showProfile: true })
    expect(seats.map((s) => [s.slot, s.isHero])).toEqual([
      ['bottom', true],
      ['top', false],
    ])
  })

  it('refuses a table size it has no layout for', () => {
    const view = { ...five.table, seats: five.table.seats.slice(0, 3) }
    expect(() => seatsFromPlayTable(view, { showProfile: true })).toThrow()
  })

  it('marks the dealer button on the is_button seat only', () => {
    const seats = seatsFromPlayTable(five.table, { showProfile: true })
    expect(seats.filter((s) => s.isButton).map((s) => s.name)).toEqual(['Bot 2'])
    expect(seats.find((s) => s.isButton)?.position).toBe('BTN')
  })

  it('flags folded seats, and shows them no cards', () => {
    const seats = seatsFromPlayTable(five.table, { showProfile: true })
    expect(seats.map((s) => s.folded)).toEqual([false, false, false, true, true])
    for (const seat of seats.filter((s) => s.folded)) expect(seat.cards).toEqual([])
  })

  it("shows Hero's cards, and every other seat's face down unless the API gave its cards", () => {
    const seats = seatsFromPlayTable(five.table, { showProfile: true })
    expect(seats[0]).toMatchObject({ cards: ['Kc', 'Jd'], faceDown: false })
    expect(seats[1]).toMatchObject({ cards: [null, null], faceDown: true })
    const shown = seatsFromPlayTable(side.table, { showProfile: true })
    expect(shown[3]).toMatchObject({ cards: ['As', 'Ac'], faceDown: false })
    expect(shown[4]).toMatchObject({ cards: ['8s', '8c'], faceDown: false })
    // folded bots stay unshown, and show nothing
    expect(shown[1]).toMatchObject({ cards: [], folded: true })
  })

  it('shows the profile badge for bots only, and only when asked', () => {
    const on = seatsFromPlayTable(five.table, { showProfile: true })
    expect(on.map((s) => s.showProfile)).toEqual([false, true, true, true, true])
    expect(on[3]?.profile?.label).toBe('TAG')
    const off = seatsFromPlayTable(five.table, { showProfile: false })
    expect(off.some((s) => s.showProfile)).toBe(false)
  })

  it('reads stacks and bets from the view, and from a frame when one is given', () => {
    const plain = seatsFromPlayTable(five.table, { showProfile: true })
    expect(plain.map((s) => s.stackChips)).toEqual(five.table.stacks)
    const frame = five.frames[4]!
    const seats = seatsFromPlayTable(five.table, { showProfile: true, frame })
    expect(seats.map((s) => s.stackChips)).toEqual(frame.stacks)
    expect(seats.map((s) => s.betChips)).toEqual([5, 5, 5, 1, 2])
    // the folded flags follow the frame too: SB folded in frame 4, BB not yet in frame 3
    expect(seats.map((s) => s.folded)).toEqual([false, false, false, true, false])
  })

  it('flags an all-in seat from a frame, and never a folded one', () => {
    const last = seatsFromPlayTable(side.table, { showProfile: true, frame: side.frames[5]! })
    expect(last.map((s) => s.allIn)).toEqual([false, false, false, true, true])
    expect(last.map((s) => s.stackChips)).toEqual([301, 194, 192, 0, 0])
    const mid = seatsFromPlayTable(side.table, { showProfile: true, frame: side.frames[4]! })
    expect(mid.map((s) => s.allIn)).toEqual([false, false, false, true, false])
  })

  it('shows no bot cards at an earlier frame, unless revealed', () => {
    const mid = seatsFromPlayTable(side.table, { showProfile: true, frame: side.frames[4]! })
    for (const seat of mid.filter((s) => !s.isHero && !s.folded)) {
      expect(seat).toMatchObject({ cards: [null, null], faceDown: true })
    }
    for (const seat of mid.filter((s) => s.folded)) {
      expect(seat).toMatchObject({ cards: [], faceDown: false })
    }
    expect(mid[0]!.cards).not.toContain(null)
    const shown = seatsFromPlayTable(side.table, {
      showProfile: true,
      frame: side.frames[5]!,
      revealed: true,
    })
    expect(shown[3]).toMatchObject({ cards: ['As', 'Ac'], faceDown: false, flip: true })
  })

  it('orders the seats from Hero clockwise when Hero is not in seat 0', () => {
    const n = 5
    const hero = 2
    const view = {
      ...five.table,
      hero_seat: hero,
      seats: five.table.seats.map((s) => ({ ...s, is_hero: s.seat === hero })),
    }
    const seats = seatsFromPlayTable(view, { showProfile: true })
    const names = (i: number) => view.seats.find((s) => s.seat === i)!.name
    expect(seats.map((s) => s.name)).toEqual(
      Array.from({ length: n }, (_, i) => names((hero + i) % n)),
    )
    expect(seats.map((s) => s.slot)).toEqual([
      'bottom',
      'bottom-left',
      'top-left',
      'top-right',
      'bottom-right',
    ])
    expect(seats[0]!.isHero).toBe(true)
  })
})
