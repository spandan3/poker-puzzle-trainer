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

  const status = page.getByRole('status').filter({ hasText: /Best|Fine|Mistake|Blunder/ })
  await expect(status).toBeVisible()
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
