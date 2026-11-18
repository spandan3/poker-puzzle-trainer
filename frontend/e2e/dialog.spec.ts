import { expect, test } from '@playwright/test'

test('the confirm dialog traps focus, and Escape returns it to the opener', async ({ page }) => {
  await page.goto('/?gallery')
  const opener = page.getByRole('button', { name: 'Open dialog' })
  await opener.scrollIntoViewIfNeeded()
  await opener.click()
  const dialog = page.getByRole('dialog', { name: 'Leave this puzzle?' })
  await expect(dialog).toBeVisible()
  await expect(page.getByRole('button', { name: 'Stay' })).toBeFocused()
  // a real modal: the dialog is :modal and the page behind it is inert
  expect(await dialog.evaluate((d) => d.matches(':modal'))).toBe(true)
  expect(await opener.evaluate((el) => (el.focus(), el.matches(':focus')))).toBe(false)

  // Focus cycles through the dialog's two buttons. After the last one Chromium passes through
  // the browser's own UI (document.body is active) and then wraps; page content behind the modal
  // is never reached.
  const outside = page.locator(':focus:not(body):not(dialog *)')
  const seen = new Set<string>()
  for (const key of ['Tab', 'Shift+Tab']) {
    seen.clear()
    for (let i = 0; i < 6; i++) {
      await page.keyboard.press(key)
      await expect(outside).toHaveCount(0)
      for (const name of ['Stay', 'Leave']) {
        if (await page.getByRole('button', { name }).evaluate((el) => el.matches(':focus'))) {
          seen.add(name)
        }
      }
    }
    expect([...seen].sort()).toEqual(['Leave', 'Stay'])
  }

  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(page.getByText('Last result: cancelled')).toBeVisible()
  await expect(opener).toBeFocused()
})
