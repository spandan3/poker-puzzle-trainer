// The page-side callbacks below run in the browser, so this file sees the DOM types.
/// <reference lib="dom" />
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { wideFont } from './helpers'

// The gallery draws every table inside the same width cap and minimum font as Puzzles and Play
// (`tableLayout.module.css`), so these are the sizes a player sees at 1024×768 and 1280×800.
const SIZES = [
  [1024, 768],
  [1280, 800],
] as const

interface Box {
  x: number
  y: number
  w: number
  h: number
}

interface TableReport {
  seats: number
  font: number
  /** pairs of boxes that overlap, as "what / with what" */
  overlaps: string[]
  /** table text below 11px */
  small: string[]
  /** table text that its box cuts off */
  clipped: string[]
  /** text that sticks out of its plate */
  stuck: string[]
  /** the smallest gap between two seats (px; negative: they overlap) */
  clearance: number
  /** how many text elements were checked (a guard against an empty selector) */
  checked: number
}

/** Measures one table: hole cards against the centre, the bets, other plates and the dealer. */
async function measure(page: Page, index: number): Promise<TableReport> {
  return page
    .locator('#table section[aria-label="Poker table"]')
    .nth(index)
    .evaluate((table) => {
      const box = (el: Element): Box => {
        const r = el.getBoundingClientRect()
        return { x: r.x, y: r.y, w: r.width, h: r.height }
      }
      // overlap by more than half a pixel in both directions
      const meet = (a: Box, b: Box) =>
        Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 0.5 &&
        Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > 0.5

      const seats = [...table.querySelectorAll<HTMLElement>('[data-slot]')]
      const centre = [...table.querySelectorAll('[data-centre-budget] > *')]
        .map(box)
        .filter((b) => b.w > 2 && b.h > 2)
      const bets = seats.flatMap((seat) =>
        [...seat.querySelectorAll('[data-part="bet"]')].map((el) => ({
          seat: seat.dataset.slot,
          box: box(el),
        })),
      )
      const dealers = [...table.querySelectorAll('[aria-label="Dealer button"]')].map(box)

      const overlaps: string[] = []
      // the centre's contract: its content never touches a seat's bet or the dealer button
      for (const [j, c] of centre.entries()) {
        for (const b of bets) if (meet(c, b.box)) overlaps.push(`centre ${j} / ${b.seat} bet`)
        for (const d of dealers) if (meet(c, d)) overlaps.push(`centre ${j} / dealer button`)
      }
      for (const seat of seats) {
        const slot = seat.dataset.slot
        const cards = [...seat.querySelectorAll('[data-part="cards"] > *')].map(box)
        cards.forEach((card, i) => {
          centre.forEach(
            (c, j) => meet(card, c) && overlaps.push(`${slot} card ${i} / centre ${j}`),
          )
          bets.forEach(
            (b) => meet(card, b.box) && overlaps.push(`${slot} card ${i} / ${b.seat} bet`),
          )
          dealers.forEach(
            (d) => meet(card, d) && overlaps.push(`${slot} card ${i} / dealer button`),
          )
          for (const other of seats) {
            if (other === seat) continue
            const plate = other.querySelector('[data-part="plate"]')
            if (plate && meet(card, box(plate))) {
              overlaps.push(`${slot} card ${i} / ${other.dataset.slot} plate`)
            }
          }
        })
      }

      // a seat is its plate, hole cards, bet and dealer button; seats never touch each other, the
      // board or the pot, and every part sits inside the table box
      const tableBox = box(table)
      const parts = seats.map((seat) => ({
        slot: seat.dataset.slot,
        boxes: [
          ...seat.querySelectorAll(
            '[data-part="plate"], [data-part="cards"] > *, [data-part="bet"], [aria-label="Dealer button"]',
          ),
        ].map(box),
      }))
      const clearances: number[] = []
      for (const [i, a] of parts.entries()) {
        for (const p of a.boxes) {
          if (
            p.x < tableBox.x - 0.5 ||
            p.y < tableBox.y - 0.5 ||
            p.x + p.w > tableBox.x + tableBox.w + 0.5 ||
            p.y + p.h > tableBox.y + tableBox.h + 0.5
          ) {
            overlaps.push(`${a.slot} sticks out of the table box`)
          }
          centre.forEach((c, j) => meet(p, c) && overlaps.push(`${a.slot} seat / centre ${j}`))
        }
        for (const other of parts.slice(i + 1)) {
          for (const p of a.boxes) {
            for (const q of other.boxes) {
              if (meet(p, q)) overlaps.push(`${a.slot} seat / ${other.slot} seat`)
              const gapX = Math.max(p.x - (q.x + q.w), q.x - (p.x + p.w))
              const gapY = Math.max(p.y - (q.y + q.h), q.y - (p.y + p.h))
              clearances.push(Math.max(gapX, gapY))
            }
          }
        }
      }

      // a plate holds its rows: nothing sticks out of a plate or runs past its right edge
      const stuck: string[] = []
      for (const plate of table.querySelectorAll<HTMLElement>('[data-part="plate"]')) {
        const p = plate.getBoundingClientRect()
        for (const el of plate.querySelectorAll('span, button')) {
          const r = el.getBoundingClientRect()
          if (r.width <= 1) continue
          // the dealer button sits beside its plate, and a tooltip floats over it, on purpose
          if (el.closest('[role="tooltip"], [aria-label="Dealer button"]')) continue
          if (r.right > p.right - 2 || r.left < p.left + 2) {
            stuck.push(
              `${el.textContent!.trim().slice(0, 20)} in ${plate.textContent!.slice(0, 12)}`,
            )
          }
        }
      }

      // every text in the table, card faces apart
      const small: string[] = []
      const clipped: string[] = []
      let checked = 0
      for (const el of table.querySelectorAll('*')) {
        if (el.closest('[data-face]') || el.closest('svg')) continue
        const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent!.trim() !== '')
        if (!own) continue
        // the screen-reader-only text is clipped to 1px, and drawn nowhere
        const r = el.getBoundingClientRect()
        if (r.width <= 1 && r.height <= 1) continue
        checked++
        const px = parseFloat(getComputedStyle(el).fontSize)
        const h = el as HTMLElement
        if (h.scrollWidth > h.clientWidth + 1 && h.clientWidth > 0) {
          clipped.push(el.textContent!.trim().slice(0, 24))
        }
        if (px < 11) small.push(`${el.textContent!.trim().slice(0, 24)}: ${px}px`)
      }
      return {
        seats: seats.length,
        font: parseFloat(getComputedStyle(table.firstElementChild!).fontSize),
        overlaps: [...new Set(overlaps)],
        small,
        clipped,
        stuck,
        clearance: clearances.length ? Math.min(...clearances) : Infinity,
        checked,
      }
    })
}

for (const [width, height] of SIZES) {
  test(`table geometry at ${width}×${height}: no card overlaps, and no table text under 11px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/?gallery')
    const tables = page.locator('#table section[aria-label="Poker table"]')
    await expect(tables.first()).toBeAttached()
    const count = await tables.count()
    expect(count).toBeGreaterThanOrEqual(5)
    const seatCounts = new Set<number>()
    for (let i = 0; i < count; i++) {
      await tables.nth(i).scrollIntoViewIfNeeded()
      const report = await measure(page, i)
      seatCounts.add(report.seats)
      const where = `table ${i} (${report.seats} seats, ${report.font}px)`
      expect(report.checked, where).toBeGreaterThan(4)
      expect(report.overlaps, where).toEqual([])
      expect(report.small, where).toEqual([])
      expect(report.clipped, where).toEqual([])
      expect(report.stuck, where).toEqual([])
    }
    // the heads-up tables and the five-seat one are all covered
    expect([...seatCounts].sort()).toEqual([2, 5])
  })
}

for (const [width, height] of SIZES) {
  test(`table geometry with a wide fallback font, at ${width}×${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/?gallery')
    await wideFont(page)
    const tables = page.locator('#table section[aria-label="Poker table"]')
    await expect(tables.first()).toBeAttached()
    const count = await tables.count()
    for (let i = 0; i < count; i++) {
      await tables.nth(i).scrollIntoViewIfNeeded()
      const report = await measure(page, i)
      const where = `table ${i} (${report.seats} seats, ${report.font}px, wide font)`
      expect(report.overlaps, where).toEqual([])
      expect(report.clipped, where).toEqual([])
      expect(report.stuck, where).toEqual([])
    }
  })
}

test('the five-seat gallery tables are all drawn, and their seats keep clear of each other', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 768 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/?gallery')
  const tables = page.locator('#table section[aria-label="Poker table"]')
  await expect(tables.first()).toBeAttached()
  let fiveSeat = 0
  for (let i = 0; i < (await tables.count()); i++) {
    await tables.nth(i).scrollIntoViewIfNeeded()
    const report = await measure(page, i)
    if (report.seats !== 5) continue
    fiveSeat++
    expect(report.clearance, `table ${i}`).toBeGreaterThanOrEqual(2)
  }
  // the synthetic table, a running hand, a side-pot jam, a side-pot showdown and a Hero fold
  expect(fiveSeat).toBeGreaterThanOrEqual(6)
  // the side-pot showdown names the pots
  await expect(page.getByText('Main 253.5 bb · Side 12 bb')).toBeVisible()
})

test('the 11px text floor holds with the table at its smallest font', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 })
  await page.goto('/?gallery')
  const first = page.locator('#table section[aria-label="Poker table"]').first()
  await first.scrollIntoViewIfNeeded()
  // 9px at 1024×768: the geometry minimum, below the text floor
  const font = await first.evaluate((el) =>
    parseFloat(getComputedStyle(el.firstElementChild!).fontSize),
  )
  expect(font).toBeLessThanOrEqual(10)
  const plate = first.locator('[data-slot="top"] [data-part="plate"]')
  const name = await plate
    .locator('span')
    .first()
    .evaluate((el) => parseFloat(getComputedStyle(el).fontSize))
  expect(name).toBeGreaterThanOrEqual(11)
})
