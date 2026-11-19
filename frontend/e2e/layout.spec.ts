import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// Every page, at both sizes: no sideways page scroll, a one-row top bar (with the wide fallback
// font CI uses) and no text under 11 px except the faces of cards. Play runs on routed fixtures,
// so it needs no session on the shared database.

const SIZES = [
  [1024, 768],
  [1280, 800],
] as const

const fixtureJson = (name: string) =>
  readFileSync(resolve(import.meta.dirname, `../src/test/fixtures/${name}.json`), 'utf8')

const json = (body: string, status = 200) => ({
  status,
  contentType: 'application/json',
  body,
})

/** CI's Linux runner falls back to DejaVu Sans, a wide font; this stands in for it elsewhere. */
async function wideFont(page: Page) {
  await page.addStyleTag({
    content: 'body, button, select, input { font-family: "DejaVu Sans", sans-serif !important; }',
  })
}

async function routePuzzles(page: Page) {
  await page.route('**/api/puzzles/current', (r) =>
    r.fulfill(json(fixtureJson('puzzle_flop_unopened'))),
  )
  await page.route('**/api/puzzles/*/attempts', (r) =>
    r.fulfill(json(fixtureJson('attempt_bet'), 201)),
  )
}

async function routePlay(page: Page, hand: 'hero_to_act' | 'hand_over_showdown') {
  await page.route('**/api/play/sessions/current', (r) =>
    r.fulfill(json(fixtureJson(`play_session_${hand}`))),
  )
  await page.route('**/api/play/sessions', (r) =>
    r.request().method() === 'GET' ? r.fulfill(json(fixtureJson('play_sessions'))) : r.fallback(),
  )
  await page.route('**/api/play/hands/*/analysis', (r) =>
    r.fulfill(json(fixtureJson('play_hand_analysis'))),
  )
  await page.route('**/api/play/sessions/*/hands', (r) =>
    r.fulfill(json(fixtureJson('play_hands'))),
  )
}

/** No sideways page scroll, and the bar is one row: nothing overflows it, every control is inside it. */
async function expectPageFits(page: Page, width: number, state: string) {
  const over = await page.evaluate(() => {
    const html = document.documentElement
    return html.scrollWidth - window.innerWidth
  })
  expect(over, `${state}: the page scrolls sideways`).toBeLessThanOrEqual(0)

  const header = page.getByRole('banner')
  const bar = (await header.boundingBox())!
  const overflow = await header.evaluate((el) => el.scrollWidth - el.clientWidth)
  expect(overflow, `${state}: the bar overflows`).toBeLessThanOrEqual(0)
  const outside: string[] = []
  for (const control of await header.locator('a[href], button, select, input').all()) {
    const box = await control.boundingBox()
    if (box === null) continue
    const inBar =
      box.x >= bar.x - 0.5 &&
      box.x + box.width <= bar.x + bar.width + 0.5 &&
      box.y >= bar.y - 0.5 &&
      box.y + box.height <= bar.y + bar.height + 0.5
    const inViewport = box.x >= -0.5 && box.x + box.width <= width + 0.5
    if (!inBar || !inViewport) {
      outside.push(
        (await control.textContent()) || (await control.getAttribute('aria-label')) || '?',
      )
    }
  }
  expect(outside, `${state}: controls outside the bar`).toEqual([])
}

/** Every visible text is at least 11 px, except what is drawn on a card face. */
async function expectTextFloor(page: Page, state: string) {
  const small = await page.evaluate(() => {
    const floor = 11
    const found: string[] = []
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = node.textContent?.trim()
      const el = node.parentElement
      if (!text || !el || el.closest('[data-face]')) continue
      if (el.closest('script, style, noscript, [hidden], [aria-hidden="true"] [data-sr]')) continue
      const style = getComputedStyle(el)
      if (style.display === 'none' || style.visibility === 'hidden') continue
      const range = document.createRange()
      range.selectNodeContents(node)
      const rect = range.getBoundingClientRect()
      // a visually hidden text (a screen-reader label) has no size to read: it sits in a 1 px box
      if (rect.width < 2 || rect.height < 2) continue
      let clipped = false
      for (let a: Element | null = el; a && a !== document.body; a = a.parentElement) {
        const box = a.getBoundingClientRect()
        const cs = getComputedStyle(a)
        if (box.width <= 2 && box.height <= 2 && cs.overflow !== 'visible') clipped = true
      }
      if (clipped) continue
      let size = parseFloat(style.fontSize)
      // SVG text is in user units: its drawn size is scaled by the figure's transform
      if (el instanceof SVGGraphicsElement) {
        const ctm = el.getScreenCTM()
        if (ctm) size *= ctm.a
      }
      if (size < floor - 0.01) found.push(`${size.toFixed(2)}px "${text.slice(0, 30)}"`)
    }
    return found
  })
  expect(small, `${state}: text under 11 px`).toEqual([])
}

async function check(page: Page, width: number, state: string) {
  await expectPageFits(page, width, state)
  await expectTextFloor(page, state)
}

for (const [width, height] of SIZES) {
  const at = `${width}×${height}`

  test.describe(`layout at ${at}`, () => {
    test.use({ viewport: { width, height } })

    test('Puzzles: fresh, filled, and every result tab', async ({ page }) => {
      await routePuzzles(page)
      await page.goto('/')
      await wideFont(page)
      await expect(page.getByRole('textbox', { name: 'Equity' })).toBeVisible()
      await check(page, width, `Puzzles fresh ${at}`)

      await page.getByRole('textbox', { name: 'Equity' }).fill('50')
      await page.keyboard.press('Escape')
      const action = page.locator('[aria-label="Action"] button:not([aria-disabled])').first()
      await action.click()
      const kind = await action.getAttribute('data-kind')
      if (kind === 'bet' || kind === 'raise') {
        await page.getByRole('group', { name: 'Size' }).getByRole('button').first().click()
      }
      await check(page, width, `Puzzles filled ${at}`)

      await page.getByRole('button', { name: /^Submit/ }).click()
      await expect(page.getByRole('region', { name: 'Result' })).toBeVisible()
      for (const tab of ['Why', 'Options', 'Maths', 'Range', 'Hand']) {
        await page.getByRole('tab', { name: tab }).click()
        await check(page, width, `Puzzles result ${tab} ${at}`)
      }
    })

    test('Play: start, hand, hand over, and the analysis', async ({ page }) => {
      // start: no open session
      await page.route('**/api/play/sessions/current', (r) =>
        r.fulfill(json(JSON.stringify({ detail: 'no open session' }), 404)),
      )
      await page.route('**/api/play/sessions', (r) =>
        r.request().method() === 'GET'
          ? r.fulfill(json(fixtureJson('play_sessions')))
          : r.fallback(),
      )
      await page.goto('/play')
      await wideFont(page)
      await expect(page.getByRole('button', { name: 'Start session' })).toBeVisible()
      await check(page, width, `Play start ${at}`)
      await page.unroute('**/api/play/sessions/current')

      await routePlay(page, 'hero_to_act')
      await page.reload()
      await wideFont(page)
      await expect(page.getByRole('form', { name: 'Your answer' })).toBeVisible()
      await check(page, width, `Play hand ${at}`)

      await page.unroute('**/api/play/sessions/current')
      await page.route('**/api/play/sessions/current', (r) =>
        r.fulfill(json(fixtureJson('play_session_hand_over_showdown'))),
      )
      await page.reload()
      await wideFont(page)
      await expect(page.getByRole('button', { name: 'Analyse this hand' })).toBeVisible()
      await check(page, width, `Play hand over ${at}`)

      await page.getByRole('button', { name: 'Analyse this hand' }).click()
      await expect(page.getByRole('region', { name: 'Summary' })).toBeVisible()
      await check(page, width, `Play analysis ${at}`)
      for (const tab of ['Why', 'Options', 'Maths', 'Range', 'Hand']) {
        await page.getByRole('tab', { name: tab, exact: true }).click()
        await check(page, width, `Play analysis ${tab} ${at}`)
      }
    })

    test('Progress and Settings', async ({ page }) => {
      await page.goto('/progress')
      await wideFont(page)
      await expect(page.getByRole('heading', { name: 'Progress' }).first()).toBeVisible()
      await check(page, width, `Progress ${at}`)
      await page.goto('/settings')
      await wideFont(page)
      await expect(page.getByRole('heading', { name: 'Settings' }).first()).toBeVisible()
      await check(page, width, `Settings ${at}`)
    })
  })
}
