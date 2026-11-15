import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'

const FACE_UP = { name: / of (spades|hearts|diamonds|clubs)$/ }

// One database serves the whole run, so every test leaves no session open.
async function endOpenSession(request: APIRequestContext) {
  const current = await request.get('/api/play/sessions/current')
  if (current.ok()) {
    const { id } = (await current.json()) as { id: number }
    await request.post(`/api/play/sessions/${id}/end`)
  }
}

test.beforeEach(async ({ request }) => endOpenSession(request))
test.afterEach(async ({ request }) => endOpenSession(request))

const nextButton = (page: Page) => page.getByRole('button', { name: /^(Next hand|Rebuy and deal)/ })
const actionForm = (page: Page) => page.getByRole('form', { name: 'Your answer' })

/** Plays the current hand by clicking the first enabled action (and first size) until it is over. */
async function playToTheEnd(page: Page) {
  const form = actionForm(page)
  const enabled = form.locator('button[data-kind]:not([aria-disabled])').first()
  for (let i = 0; i < 20; i++) {
    await expect(enabled.or(nextButton(page))).toBeVisible({ timeout: 20_000 })
    if (await nextButton(page).isVisible()) return
    await enabled.click()
    const kind = await enabled.getAttribute('data-kind')
    if (kind === 'bet' || kind === 'raise') {
      await page.getByRole('group', { name: 'Size' }).getByRole('button').first().click()
    }
    await page.getByRole('button', { name: /^Submit/ }).click()
    // the form is busy while the request runs and the bot's actions are shown one by one
    await expect(page.locator('form[aria-label="Your answer"][aria-busy="true"]')).toHaveCount(0, {
      timeout: 20_000,
    })
  }
  throw new Error('the hand did not end')
}

/** Deals hands (N) until Hero is to act in one. */
async function dealUntilHeroActs(page: Page) {
  // a Next button that is busy (aria-disabled) is the previous hand's, still waiting for the deal
  const nextReady = page.locator('button:not([aria-disabled])', {
    hasText: /^(Next hand|Rebuy and deal)/,
  })
  for (let i = 0; i < 10; i++) {
    await expect(actionForm(page).or(nextReady)).toBeVisible({ timeout: 20_000 })
    if (await actionForm(page).isVisible()) {
      // wait out the bot's reveal
      await expect(page.locator('form[aria-label="Your answer"][aria-busy="true"]')).toHaveCount(
        0,
        { timeout: 20_000 },
      )
      if (await actionForm(page).isVisible()) return
    }
    await nextReady.click()
  }
  throw new Error('Hero never got to act')
}

test('a session end to end: start, play hands, tally, next hand, resume, end', async ({ page }) => {
  await page.goto('/play')
  await expect(page).toHaveTitle('Play · Poker Puzzle Trainer')
  await expect(page.getByText(/^Pre-flop, the bot responds the same way/)).toBeVisible()
  await page.getByRole('button', { name: 'Start session' }).click()

  const hero = page.getByRole('group', { name: /^Hero,/ })
  const villain = page.getByRole('group', { name: /^Villain,/ })
  await expect(hero.getByRole('img', FACE_UP)).toHaveCount(2)
  await expect(villain.getByRole('img', { name: 'face-down card' })).toHaveCount(2)
  // the tally is on the bar from the start (a bot that folds first ends hand one at once)
  await expect(page.getByLabel('Session tally')).toHaveText(/^[+−]?\d+(\.5)? bb · [01] hands?$/)

  // the first hand, to its end
  await playToTheEnd(page)
  await expect(page.getByRole('status').filter({ hasText: /won|Split pot|gave up/ })).toHaveText(
    /^(You won|Villain won) \d+(\.5)? bb( at showdown)?$|^Split pot$/,
  )
  await expect(page.getByLabel('Session tally')).toHaveText(/^[+−]?\d+(\.5)? bb · 1 hand$/)
  await expect(nextButton(page)).toBeFocused()

  // N deals the next hand
  await page.keyboard.press('n')
  await dealUntilHeroActs(page)
  await expect(page.getByText('Hero to act')).toBeVisible()

  // reload mid-hand: the same cards and the same history
  const cards = await hero.getByRole('img').evaluateAll((els) => els.map((e) => e.ariaLabel))
  const history = await page.getByRole('complementary').innerText()
  await page.reload()
  await expect(actionForm(page)).toBeVisible()
  expect(await hero.getByRole('img').evaluateAll((els) => els.map((e) => e.ariaLabel))).toEqual(
    cards,
  )
  expect(await page.getByRole('complementary').innerText()).toBe(history)

  // end the session: the start panel lists it
  await page.getByRole('button', { name: 'End session' }).click()
  await expect(page.getByRole('button', { name: 'Start session' })).toBeVisible()
  const past = page.getByRole('list', { name: 'Past sessions' })
  await expect(past.getByRole('listitem').first()).toContainText(/\d+ hands?/)
  await expect(page.getByLabel('Session tally')).toHaveCount(0)
})

test('layout: the top bar stays one row at 1280 on Play with a wide fallback font', async ({
  page,
  request,
}) => {
  // a session open, so the bar carries its longest content: the tally and End session
  const started = await request.post('/api/play/sessions')
  expect(started.ok()).toBe(true)
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/play')
  await page.addStyleTag({
    content: 'body, button, select, input { font-family: "DejaVu Sans", sans-serif !important; }',
  })
  const header = page.locator('header')
  await expect(header.getByRole('button', { name: 'End session' })).toBeVisible()
  const box = await header.boundingBox()
  expect(box!.height).toBeLessThan(70)
})
