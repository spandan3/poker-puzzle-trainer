import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { endOpenSession } from './helpers'

const FACE_UP = { name: / of (spades|hearts|diamonds|clubs)$/ }

// One database serves the whole run, so every test leaves no session open.

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
  const dialog = page.getByRole('dialog', { name: 'End this session?' })
  await expect(dialog).toBeVisible()
  // Keep playing leaves the hand as it was; End session in the dialog ends it
  await dialog.getByRole('button', { name: 'Keep playing' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(actionForm(page)).toBeVisible()
  await page.getByRole('button', { name: 'End session' }).click()
  await dialog.getByRole('button', { name: 'End session' }).click()
  await expect(page.getByRole('button', { name: 'Start session' })).toBeVisible()
  const past = page.getByRole('table', { name: 'Past sessions' })
  await expect(past.getByRole('row').nth(1)).toContainText(/\d+/)
  await expect(page.getByLabel('Session tally')).toHaveCount(0)
})

test('analyse a hand: progress, summary, every tab, close, and reopen it from the hand list', async ({
  page,
}) => {
  await page.goto('/play')
  await page.getByRole('button', { name: 'Start session' }).click()

  // a hand in which Hero acted at least once (a bot that folds first gives none to analyse)
  await dealUntilHeroActs(page)
  await playToTheEnd(page)
  await page.getByRole('button', { name: 'Analyse this hand' }).click()

  // the real backend grades each decision; allow it time
  const summary = page.getByRole('region', { name: 'Summary' })
  await expect(summary).toBeVisible({ timeout: 60_000 })
  // the analysis replaces the table
  await expect(page.getByRole('group', { name: /^Hero,/ })).toHaveCount(0)
  await expect(summary).toContainText(/Total EV lost: \d+(\.\d+)? bb/)
  const steps = page.getByRole('list', { name: 'Decisions' }).getByRole('button')
  await steps.first().click()
  for (const tab of ['Why', 'Options', 'Maths', 'Range', 'Hand']) {
    await page.getByRole('tab', { name: tab, exact: true }).click()
    await expect(page.getByRole('tabpanel')).toBeVisible()
  }
  // no guess scores in play
  await expect(page.getByText(/range read|your guess/i)).toHaveCount(0)

  // close: the hand-over panel is back, and the next hand is dealt
  await page.getByRole('button', { name: 'Close analysis' }).click()
  await expect(summary).toHaveCount(0)
  await expect(nextButton(page)).toBeVisible()
  await nextButton(page).click()
  await dealUntilHeroActs(page)

  // the analysed hand opens again from the session's hand list, from what was stored
  const posts: string[] = []
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url().includes('/analysis/')) posts.push(r.url())
  })
  const hands = page.getByRole('button', { name: /^Session hands/ })
  await expect(hands).toHaveAttribute('aria-expanded', 'false')
  await hands.click()
  await expect(hands).toHaveAttribute('aria-expanded', 'true')
  await page.getByRole('button', { name: /^Review hand \d+$/ }).click()
  await expect(summary).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText(/^Analysing decision/)).toHaveCount(0)
  expect(posts).toEqual([])
})

test('at 1024×768 the options table in the analysis does not scroll sideways', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 })
  await page.goto('/play')
  await page.getByRole('button', { name: 'Start session' }).click()
  await dealUntilHeroActs(page)
  await playToTheEnd(page)
  await page.getByRole('button', { name: 'Analyse this hand' }).click()
  await expect(page.getByRole('region', { name: 'Summary' })).toBeVisible({ timeout: 60_000 })
  await page.getByRole('list', { name: 'Decisions' }).getByRole('button').first().click()
  await page.getByRole('tab', { name: 'Options', exact: true }).click()
  const panel = page.getByRole('tabpanel')
  await expect(panel.getByRole('table')).toBeVisible()
  // the tab panel is the options table's scroll box (DecisionDetails.module.css)
  const [scrollWidth, clientWidth] = await panel.evaluate((el) => [el.scrollWidth, el.clientWidth])
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth)
})
