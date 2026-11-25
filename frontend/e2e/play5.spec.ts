import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { endOpenSession, expectBarFits, wideFont } from './helpers'

// 5-max Play: one live hand through the real backend (there is no seeded hook, so the test is
// built to hold for any deal), and the table's layout states on routed `play5_*` fixtures.

const SIZES = [
  [1024, 768],
  [1280, 800],
] as const

const FACE_UP = { name: / of (spades|hearts|diamonds|clubs)$/ }

const fixtureJson = (name: string) =>
  readFileSync(resolve(import.meta.dirname, `../src/test/fixtures/${name}.json`), 'utf8')

const json = (body: string, status = 200) => ({
  status,
  contentType: 'application/json',
  body,
})

const actionForm = (page: Page) => page.getByRole('form', { name: 'Your answer' })
const handOver = (page: Page) => page.getByRole('region', { name: 'Hand over' })

test.describe('5-max, live', () => {
  // one database serves the whole run, so no test leaves a session open
  test.beforeEach(async ({ request }) => endOpenSession(request))
  test.afterEach(async ({ request }) => endOpenSession(request))

  test('a 5-max hand to its end: five seats, hidden bot cards, named actions, pot lines', async ({
    page,
  }) => {
    // the live hand paces the bots' actions, so it takes a while
    test.setTimeout(120_000)
    await page.goto('/play')
    const modes = page.getByRole('radiogroup', { name: 'Table' })
    await modes.getByRole('radio', { name: '5-max' }).click()
    await expect(modes.getByRole('radio', { name: '5-max' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    await page.getByRole('button', { name: 'Start session' }).click()

    const hero = page.getByRole('group', { name: /^You,/ })
    const bots = page.getByRole('group', { name: /^Bot \d,/ })
    // the bots' cards are face down as the hand starts: look at once, before any reveal ends
    await expect(bots.getByRole('img', { name: 'face-down card' }).first()).toBeVisible()
    // five seats: Hero and four bots
    await expect(hero).toHaveCount(1)
    await expect(bots).toHaveCount(4)
    await expect(hero.getByRole('img', FACE_UP)).toHaveCount(2)

    let handEnded = false
    // Hero checks or calls (folds only when neither is on offer) until the hand is over; a bounded
    // number of actions, whatever the deal
    for (let i = 0; i < 40 && !handEnded; i++) {
      await expect(actionForm(page).or(handOver(page))).toBeVisible({ timeout: 30_000 })
      if (await handOver(page).isVisible()) {
        handEnded = true
        break
      }
      // the bots' actions are shown one by one: wait until Hero can act
      await expect(page.locator('form[aria-label="Your answer"][aria-busy="true"]')).toHaveCount(
        0,
        { timeout: 30_000 },
      )
      if (!(await actionForm(page).isVisible())) continue
      // while the hand runs, no bot card is face up
      const faceUp = await bots.getByRole('img', FACE_UP).count()
      expect(faceUp, 'a bot card is face up during the hand').toBe(0)
      let clicked = false
      for (const kind of ['check', 'call', 'fold']) {
        const button = actionForm(page).locator(`button[data-kind="${kind}"]:not([aria-disabled])`)
        if ((await button.count()) === 0) continue
        await button.first().click()
        clicked = true
        break
      }
      if (!clicked) {
        // none of the three: take the first enabled action (and its first size)
        const enabled = actionForm(page).locator('button[data-kind]:not([aria-disabled])').first()
        await enabled.click()
        const kind = await enabled.getAttribute('data-kind')
        if (kind === 'bet' || kind === 'raise') {
          await page.getByRole('group', { name: 'Size' }).getByRole('button').first().click()
        }
      }
      const logBefore = await page.getByRole('complementary').innerText()
      await page.getByRole('button', { name: /^Submit/ }).click()
      // Hero's action reached the log (or the hand ended) before the next loop reads the page
      await expect
        .poll(
          async () =>
            (await handOver(page).isVisible()) ||
            (await page.getByRole('complementary').innerText()) !== logBefore,
          { timeout: 30_000 },
        )
        .toBe(true)
      await expect(page.locator('form[aria-label="Your answer"][aria-busy="true"]')).toHaveCount(
        0,
        { timeout: 30_000 },
      )
    }
    expect(handEnded, 'the hand did not end in 40 actions').toBe(true)

    // the action log names the bots
    await expect(page.getByRole('complementary')).toContainText(
      /Bot \d.{0,12}(folds|calls|checks|bets|raises)/,
    )
    // the hand-over panel: a result, at least one pot line, no Analyse
    const over = handOver(page)
    await expect(over.getByRole('status')).toBeVisible()
    await expect(over.getByRole('list', { name: 'Pots' }).getByRole('listitem')).not.toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Analyse this hand' })).toHaveCount(0)
    await expect(page.getByRole('group', { name: /^(You|Bot \d),/ })).toHaveCount(5)
    // at a showdown the bots that showed are face up (two cards each) once the reveal is over
    const current = await page.request.get('/api/play/sessions/current')
    const outcome = ((await current.json()) as { hand: { outcome: { shown: { seat: number }[] } } })
      .hand.outcome
    for (const { seat } of outcome.shown) {
      if (seat === 0) continue
      await expect(
        page.getByRole('group', { name: new RegExp(`^Bot ${seat},`) }).getByRole('img', FACE_UP),
      ).toHaveCount(2)
    }

    // end the session
    await page.getByRole('button', { name: 'End session' }).click()
    // between hands the session ends at once; the dialog only guards a hand in play
    const dialog = page.getByRole('dialog', { name: 'End this session?' })
    const start = page.getByRole('button', { name: 'Start session' })
    await expect(dialog.or(start)).toBeVisible()
    if (await dialog.isVisible()) await dialog.getByRole('button', { name: 'End session' }).click()
    await expect(page.getByRole('button', { name: 'Start session' })).toBeVisible()
  })
})

async function routePlay5(page: Page, session: 'hero_to_act' | 'side_pot' | 'hero_folded') {
  await page.route('**/api/play/sessions/current', (r) =>
    r.fulfill(json(fixtureJson(`play5_session_${session}`))),
  )
  await page.route('**/api/play/sessions', (r) =>
    r.request().method() === 'GET' ? r.fulfill(json(fixtureJson('play5_sessions'))) : r.fallback(),
  )
  await page.route('**/api/play/sessions/*/hands', (r) =>
    r.fulfill(json(fixtureJson('play5_hands'))),
  )
}

/** No page scroll in either direction, a one-row bar, and no seat or control cut off. */
async function expectFits(page: Page, width: number, height: number, state: string) {
  const over = await page.evaluate(() => {
    const html = document.documentElement
    return {
      x: html.scrollWidth - window.innerWidth,
      y: html.scrollHeight - window.innerHeight,
    }
  })
  expect(over.x, `${state}: the page scrolls sideways`).toBeLessThanOrEqual(0)
  expect(over.y, `${state}: the page scrolls down`).toBeLessThanOrEqual(0)
  await expectBarFits(page, width, state)
  // every seat plate, and the action or hand-over controls, are inside the viewport
  const outside: string[] = []
  const parts = page.locator(
    'section[aria-label="Poker table"] [data-slot] [data-part="plate"], [aria-label="Your answer"] button, [aria-label="Hand over"] button',
  )
  for (const part of await parts.all()) {
    const box = await part.boundingBox()
    if (box === null) continue
    if (
      box.x < -0.5 ||
      box.y < -0.5 ||
      box.x + box.width > width + 0.5 ||
      box.y + box.height > height + 0.5
    ) {
      outside.push((await part.textContent())?.slice(0, 20) ?? '?')
    }
  }
  expect(outside, `${state}: parts outside the viewport`).toEqual([])
  // seats do not overlap each other
  const plates = await page
    .locator('section[aria-label="Poker table"] [data-slot] [data-part="plate"]')
    .all()
  const boxes = []
  for (const plate of plates) boxes.push((await plate.boundingBox())!)
  expect(boxes.length, `${state}: five seats`).toBe(5)
  for (const [i, a] of boxes.entries()) {
    for (const b of boxes.slice(i + 1)) {
      const w = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)
      const h = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y)
      expect(w > 0.5 && h > 0.5, `${state}: two seat plates overlap`).toBe(false)
    }
  }
}

for (const [width, height] of SIZES) {
  const at = `${width}×${height}`
  test.describe(`5-max layout at ${at}`, () => {
    test.use({ viewport: { width, height } })

    test('a running hand', async ({ page }) => {
      await routePlay5(page, 'hero_to_act')
      await page.goto('/play')
      await wideFont(page)
      await expect(actionForm(page)).toBeVisible()
      await expect(page.getByRole('group', { name: /^Bot \d,/ })).toHaveCount(4)
      await expectFits(page, width, height, `5-max hand ${at}`)
    })

    test('a showdown with side pots', async ({ page }) => {
      await routePlay5(page, 'side_pot')
      await page.goto('/play')
      await wideFont(page)
      await expect(handOver(page)).toBeVisible()
      await expect(page.getByRole('list', { name: 'Pots' }).getByRole('listitem')).toHaveCount(2)
      await expectFits(page, width, height, `5-max showdown ${at}`)
    })

    test('Hero folded, two bots in the hand', async ({ page }) => {
      await routePlay5(page, 'hero_folded')
      await page.goto('/play')
      await wideFont(page)
      await expect(handOver(page)).toBeVisible()
      await expect(page.getByRole('group', { name: /^Bot \d,/ })).toHaveCount(4)
      await expectFits(page, width, height, `5-max Hero folded ${at}`)
    })
  })
}
