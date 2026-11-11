import { expect, test } from '@playwright/test'

test('the API is up and serves the built frontend', async ({ page, request }) => {
  const res = await request.get('/api/health')
  expect(res.ok()).toBe(true)
  expect(await res.json()).toMatchObject({ status: 'ok' })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Poker Puzzle Trainer' })).toBeVisible()
  await expect(page.getByTestId('status')).toContainText('API version')
})
