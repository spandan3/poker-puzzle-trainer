import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const FACE_UP = { name: / of (spades|hearts|diamonds|clubs)$/ }

test('the API is up and serves the built frontend', async ({ request }) => {
  const res = await request.get('/api/health')
  expect(res.ok()).toBe(true)
  expect(await res.json()).toMatchObject({ status: 'ok' })
})

test('a puzzle end to end: answer, submit, verdict, reveal, next', async ({ page }) => {
  await page.goto('/')
  const hero = page.getByRole('group', { name: /^Hero,/ })
  const villain = page.getByRole('group', { name: /^Villain,/ })
  await expect(hero.getByRole('img', FACE_UP)).toHaveCount(2)
  await expect(villain.getByRole('img', { name: 'face-down card' })).toHaveCount(2)

  await page.getByRole('textbox', { name: 'Equity' }).fill('50')
  await page.keyboard.press('Escape')
  // the first enabled action, and for a bet or raise its first size
  const action = page.locator('[aria-label="Action"] button:not([aria-disabled])').first()
  await action.click()
  const kind = await action.getAttribute('data-kind')
  if (kind === 'bet' || kind === 'raise') {
    await page.getByRole('group', { name: 'Size' }).getByRole('button').first().click()
  }
  await page.getByRole('button', { name: /^Submit/ }).click()

  await expect(page.getByRole('region', { name: 'Result' })).toContainText(
    /Best|Fine|Mistake|Blunder/,
  )
  await expect(page.getByTestId('announcer')).toHaveText(/^(Best|Fine|Mistake|Blunder)\. You: /)
  await expect(villain.getByRole('img', { name: 'face-down card' })).toHaveCount(0)
  await expect(villain.getByRole('img', FACE_UP)).toHaveCount(2)
  await expect(page.getByText('your answer')).toBeVisible()
  await expect(page.getByRole('button', { name: /Next puzzle/ })).toBeFocused()

  // the details: one landmark in each tab
  const panel = page.getByRole('tabpanel')
  await page.getByRole('tab', { name: 'Why' }).click()
  await expect(panel.locator('p').first()).not.toBeEmpty()
  await expect(panel.getByRole('heading', { level: 3 }).first()).toBeVisible()
  await page.getByRole('tab', { name: 'Options' }).click()
  await expect(panel.getByRole('table')).toBeVisible()
  await page.getByRole('tab', { name: 'Maths' }).click()
  await expect(panel.getByRole('heading', { level: 3 }).first()).toBeVisible()
  await page.getByRole('tab', { name: 'Range' }).click()
  await expect(panel.getByRole('heading', { level: 3 }).first()).toBeVisible()
  await page.getByRole('tab', { name: 'Hand' }).click()
  await expect(panel.getByRole('heading', { level: 3, name: 'Villain' })).toBeVisible()
  await expect(panel.getByRole('group', { name: "Villain's hand" }).getByRole('img')).toHaveCount(2)
  await page.getByRole('button', { name: /Next puzzle/ }).focus()

  await page.keyboard.press('n')
  await expect(page.getByRole('textbox', { name: 'Equity' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Equity' })).toHaveValue('')
  await expect(villain.getByRole('img', { name: 'face-down card' })).toHaveCount(2)
  await expect(page.getByText('Hero to act')).toBeVisible()
})

test('reduced motion: cards do not animate', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  const card = page
    .getByRole('group', { name: /^Hero,/ })
    .getByRole('img')
    .first()
  await expect(card).toBeVisible()
  const timing = await card.evaluate((el) => {
    const style = el.ownerDocument.defaultView!.getComputedStyle(el)
    return { duration: style.animationDuration, name: style.animationName }
  })
  expect(timing.name === 'none' || timing.duration === '0s').toBe(true)
})

test('layout: the tallest answer panel fits 1280×800, even with an error showing', async ({
  page,
}) => {
  // the widest size row: five sizes plus the custom box, served from the fixture
  const view = readFileSync(
    resolve(import.meta.dirname, '../src/test/fixtures/puzzle_flop_unopened.json'),
    'utf8',
  )
  await page.route('**/api/puzzles/current', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: view }),
  )
  await page.route('**/api/puzzles/*/attempts', (route) =>
    route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({
        detail:
          'Villain model changed since this puzzle was generated; custom sizes are disabled for this puzzle',
      }),
    }),
  )
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Equity' }).fill('40')
  await page.keyboard.press('Escape')
  await page.keyboard.press('b')
  await page.keyboard.press('1')
  const height = () => page.locator('html').evaluate((el) => el.scrollHeight)
  const width = () => page.locator('html').evaluate((el) => el.scrollWidth)
  expect(await height()).toBe(800)
  await page.getByRole('button', { name: /^Submit/ }).click()
  await expect(page.getByRole('alert')).toContainText('Villain model changed')
  expect(await height()).toBe(800)
  expect(await width()).toBe(1280)
})

for (const [width, height] of [
  [1024, 768],
  [1280, 800],
] as const) {
  test(`result page: no horizontal scroll at ${width}×${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const fixtureText = (name: string) =>
      readFileSync(resolve(import.meta.dirname, `../src/test/fixtures/${name}.json`), 'utf8')
    // the widest options table: a custom size among the standard ones
    await page.route('**/api/puzzles/current', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: fixtureText('puzzle_custom_allowed'),
      }),
    )
    await page.route('**/api/puzzles/*/attempts', (route) =>
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: fixtureText('attempt_custom'),
      }),
    )
    await page.goto('/')
    await page.getByRole('textbox', { name: 'Equity' }).fill('50')
    await page.keyboard.press('Escape')
    await page.locator('[aria-label="Action"] button:not([aria-disabled])').first().click()
    const size = page.getByRole('group', { name: 'Size' }).getByRole('button')
    if (await size.count()) await size.first().click()
    await page.getByRole('button', { name: /^Submit/ }).click()
    await expect(page.getByRole('region', { name: 'Result' })).toBeVisible()
    for (const tab of ['Why', 'Options', 'Maths', 'Range', 'Hand']) {
      await page.getByRole('tab', { name: tab }).click()
      const overflow = await page.locator('html').evaluate((el) => el.scrollWidth - el.clientWidth)
      expect(overflow, `${tab} tab`).toBeLessThanOrEqual(0)
    }
  })
}

/** Answers the first action and submits, leaving the result on screen. */
async function submitAnyAnswer(page: Page) {
  await page.getByRole('textbox', { name: 'Equity' }).fill('50')
  await page.keyboard.press('Escape')
  await page.locator('[aria-label="Action"] button:not([aria-disabled])').first().click()
  const size = page.getByRole('group', { name: 'Size' }).getByRole('button')
  if (await size.count()) await size.first().click()
  await page.getByRole('button', { name: /^Submit/ }).click()
  await expect(page.getByRole('region', { name: 'Result' })).toBeVisible()
}

test('Why tab: pending line, then the local model’s text and its footer', async ({ page }) => {
  const read = (name: string) =>
    readFileSync(resolve(import.meta.dirname, `../src/test/fixtures/${name}.json`), 'utf8')
  const settings = {
    ...JSON.parse(read('settings')),
    llm_status: 'ready',
    llm_model: 'llama3.2:3b',
  }
  await page.route('**/api/settings', (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(settings),
        })
      : route.fallback(),
  )
  await page.route('**/api/attempts/*/explanation', async (route) => {
    await new Promise((r) => setTimeout(r, 800))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: read('explanation_llm'),
    })
  })
  await page.goto('/')
  await submitAnyAnswer(page)
  const panel = page.getByRole('tabpanel')
  await page.getByRole('tab', { name: 'Why' }).click()
  await expect(panel.getByRole('status')).toHaveText('Rewriting in plain English with llama3.2:3b…')
  await expect(panel.getByText(/^In short: /)).toBeVisible()
  await expect(panel.getByRole('status')).toHaveCount(0)
  await expect(panel.getByText(/^Reworded by llama3\.2:3b, a local model\./)).toBeVisible()
})

test('progress page: no dead space below the content at 1280×800', async ({ page }) => {
  const stats = readFileSync(
    resolve(import.meta.dirname, '../src/test/fixtures/stats.json'),
    'utf8',
  )
  await page.route('**/api/stats*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: stats }),
  )
  await page.goto('/progress')
  await expect(page.getByTestId('progress-totals')).toBeVisible()
  const scrollHeight = await page.locator('html').evaluate((el) => el.scrollHeight)
  const bottom = await page
    .getByTestId('progress-page')
    .evaluate(
      (el) => el.getBoundingClientRect().bottom + el.ownerDocument.documentElement.scrollTop,
    )
  expect(scrollHeight - Math.max(bottom, 800)).toBeLessThanOrEqual(50)
})

/** Answers the puzzle on screen: equity 50, the first enabled action (and its first size). */
async function answerOnScreen(page: Page) {
  await page.getByRole('textbox', { name: 'Equity' }).fill('50')
  await page.keyboard.press('Escape')
  const action = page.locator('[aria-label="Action"] button:not([aria-disabled])').first()
  await action.click()
  const kind = await action.getAttribute('data-kind')
  if (kind === 'bet' || kind === 'raise') {
    await page.getByRole('group', { name: 'Size' }).getByRole('button').first().click()
  }
  await page.getByRole('button', { name: /^Submit/ }).click()
  await expect(page.getByRole('region', { name: 'Result' })).toBeVisible()
}

/** The Progress totals line as numbers (the DB is shared across tests, so tests compare). */
async function totals(page: Page) {
  const text = await page.getByTestId('progress-totals').innerText()
  const match = /(\d+) puzzles? answered · (\d+) practice attempts?/.exec(text)
  if (!match) throw new Error(`unexpected totals: ${text}`)
  return { answered: Number(match[1]), practice: Number(match[2]) }
}

/** The totals line as the page words it ("1 puzzle", "2 puzzles"). */
function totalsText(answered: number, practice: number) {
  return `${answered} ${answered === 1 ? 'puzzle' : 'puzzles'} answered · ${practice} practice ${practice === 1 ? 'attempt' : 'attempts'}`
}

test('replay from history is practice: it shows in history and changes no stat', async ({
  page,
}) => {
  await page.goto('/')
  await answerOnScreen(page)
  await page.getByRole('link', { name: 'Progress' }).click()
  await expect(page.getByTestId('progress-totals')).toBeVisible()
  const before = await totals(page)
  expect(before.answered).toBeGreaterThan(0)

  // the newest row is the attempt just made: replay it
  const history = page.getByTestId('history')
  await expect(history.getByRole('row').nth(1)).toBeVisible()
  await history
    .getByRole('button', { name: /^Replay puzzle from / })
    .first()
    .click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByTestId('practice-note')).toHaveText(
    "Practice — this attempt won't count toward your stats.",
  )
  await answerOnScreen(page)

  await page.getByRole('link', { name: 'Progress' }).click()
  await expect(page.getByTestId('progress-totals')).toHaveText(
    totalsText(before.answered, before.practice + 1),
  )
  await expect(
    page.getByTestId('history').getByRole('row').nth(1).getByText('Practice'),
  ).toBeVisible()

  // Result reopens the stored result, and Next puzzle is focused
  await page
    .getByTestId('history')
    .getByRole('button', { name: /^Result of the attempt from / })
    .first()
    .click()
  await expect(page.getByRole('region', { name: 'Result' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Next puzzle/ })).toBeFocused()
})

for (const [width, height] of [
  [1024, 768],
  [1280, 800],
] as const) {
  test(`progress page: no horizontal scroll at ${width}×${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const fixtureText = (name: string) =>
      readFileSync(resolve(import.meta.dirname, `../src/test/fixtures/${name}.json`), 'utf8')
    await page.route('**/api/stats*', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: fixtureText('stats') }),
    )
    await page.route('**/api/history*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: fixtureText('history_page'),
      }),
    )
    await page.goto('/progress')
    await expect(page.getByTestId('progress-totals')).toBeVisible()
    await expect(page.getByTestId('history').getByRole('row')).toHaveCount(26)
    const overflow = await page.locator('html').evaluate((el) => el.scrollWidth - el.clientWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })
}

test('layout: the top bar stays one row at 1280 with a wide fallback font', async ({ page }) => {
  // CI's Linux runner falls back to a wider font than most desktops; DejaVu Sans stands in for it
  // (where it isn't installed the browser uses its default and the check still holds).
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/')
  await page.addStyleTag({
    content: 'body, button, select, input { font-family: "DejaVu Sans", sans-serif !important; }',
  })
  const header = page.locator('header')
  await expect(header.getByRole('button', { name: /New puzzle/ })).toBeVisible()
  const box = await header.boundingBox()
  expect(box!.height).toBeLessThan(70)
})
