import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'

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
