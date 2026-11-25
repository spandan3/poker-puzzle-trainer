// Helpers shared by the e2e specs (not a spec itself: Playwright only runs *.spec.ts).
import { expect } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'

/**
 * A wide font for the layout checks. CI runs e2e on Ubuntu, where the browser's fallback is
 * DejaVu Sans, a wide font; Verdana, about as wide, ships with macOS and Windows, so a local run
 * there is as strict. With neither installed the browser's default sans is used (narrower, so
 * a local pass is weaker than CI's).
 */
export async function wideFont(page: Page) {
  await page.addStyleTag({
    content:
      'body, button, select, input { font-family: "DejaVu Sans", Verdana, sans-serif !important; }',
  })
}

/**
 * Turns "Show Villain's range" on for this page by editing the settings it loads, so the Range
 * tab is there without touching the shared database. Call it before `page.goto`.
 */
export async function showRange(page: Page) {
  await page.route('**/api/settings', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const body = (await response.json()) as Record<string, unknown>
    return route.fulfill({ response, json: { ...body, show_range: true } })
  })
}

/**
 * The top bar is one row: nothing overflows it, and every control's box lies inside the bar and
 * the viewport (0.5 px tolerance).
 */
export async function expectBarFits(page: Page, width: number, state: string) {
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

/** One database serves the whole run: a test that opens a session ends any open one first. */
export async function endOpenSession(request: APIRequestContext) {
  const current = await request.get('/api/play/sessions/current')
  if (current.ok()) {
    const { id } = (await current.json()) as { id: number }
    await request.post(`/api/play/sessions/${id}/end`)
  }
}
