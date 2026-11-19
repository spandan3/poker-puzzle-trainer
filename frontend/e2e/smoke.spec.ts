/// <reference lib="dom" />
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

const FIT_SIZES = [
  [1024, 768],
  [1280, 800],
] as const

const fixtureJson = (name: string) =>
  readFileSync(resolve(import.meta.dirname, `../src/test/fixtures/${name}.json`), 'utf8')

/** Serves one puzzle fixture as the current puzzle; a submit answers 409, as after a model change. */
async function routePuzzle(page: Page, name: string) {
  await page.route('**/api/puzzles/current', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: fixtureJson(name) }),
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
}

/**
 * The Puzzles height budget: no page scroll in either direction, and Submit's box wholly inside
 * the viewport. `slack` is the room below the answer panel's bottom padding, in px.
 */
async function expectFits(
  page: Page,
  width: number,
  height: number,
  state: string,
  { withError = false } = {},
) {
  const fit = await page.evaluate(() => {
    const html = document.documentElement
    const form = document.querySelector('form[aria-label="Your answer"]')!.getBoundingClientRect()
    return {
      scrollHeight: html.scrollHeight,
      innerHeight: window.innerHeight,
      scrollWidth: html.scrollWidth,
      innerWidth: window.innerWidth,
      formBottom: form.bottom,
    }
  })
  expect(fit.innerHeight, state).toBe(height)
  expect(fit.scrollHeight, `${state}: vertical scroll`).toBeLessThanOrEqual(fit.innerHeight)
  expect(fit.scrollWidth, `${state}: horizontal scroll`).toBeLessThanOrEqual(fit.innerWidth)
  const submit = (await page.getByRole('button', { name: /^Submit/ }).boundingBox())!
  expect(submit.y, `${state}: Submit top`).toBeGreaterThanOrEqual(0)
  expect(submit.y + submit.height, `${state}: Submit bottom`).toBeLessThanOrEqual(height)
  expect(submit.x + submit.width, `${state}: Submit right`).toBeLessThanOrEqual(width)
  // The 16 px margin is a measurement, not a guarantee: the error wraps to 5 lines in CI's
  // DejaVu Sans, so the margin is required only where no error is showing.
  if (!withError) {
    expect(height - (fit.formBottom + 16), `${state}: slack`).toBeGreaterThanOrEqual(16)
  }
}

test('a selected action keeps its keyboard focus ring', async ({ page }) => {
  await routePuzzle(page, 'puzzle_flop_unopened')
  await page.goto('/')
  const check = page.getByRole('button', { name: /^Check/ })
  await check.focus()
  await page.keyboard.press('Space')
  await expect(check).toHaveAttribute('aria-pressed', 'true')
  await expect(check).toBeFocused()
  const shadow = await check.evaluate((el) => getComputedStyle(el).boxShadow)
  // --color-focus #8ab4ff, drawn as the outer ring beside the inset selected border
  expect(shadow).toContain('rgb(138, 180, 255)')
  expect(shadow.split('rgb(').length - 1).toBeGreaterThanOrEqual(3)
})

test('a selected size and a selected intent keep their keyboard focus ring', async ({ page }) => {
  await routePuzzle(page, 'puzzle_flop_unopened')
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Equity' }).fill('40')
  await page.keyboard.press('Escape')
  await page.keyboard.press('b')
  const size = page.getByRole('group', { name: 'Size' }).getByRole('button').first()
  const intent = page.getByRole('group', { name: 'Intent' }).getByRole('button').first()
  for (const control of [size, intent]) {
    await control.focus()
    await page.keyboard.press('Space')
    await expect(control).toHaveAttribute('aria-pressed', 'true')
    await expect(control).toBeFocused()
    const shadow = await control.evaluate((el) => getComputedStyle(el).boxShadow)
    // --color-focus #8ab4ff, drawn beside the selected state's own border
    expect(shadow).toContain('rgb(138, 180, 255)')
    expect(shadow.split('rgb(').length - 1).toBeGreaterThanOrEqual(2)
  }
})

for (const [width, height] of FIT_SIZES) {
  test(`layout: the tallest answer panel fits ${width}×${height} in every state, even with an error showing`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height })
    // the widest size row: five sizes plus the custom box, served from the fixture
    await routePuzzle(page, 'puzzle_flop_unopened')
    await page.goto('/')
    await expect(page.getByRole('textbox', { name: 'Equity' })).toBeVisible()
    await expectFits(page, width, height, 'fresh')

    await page.getByRole('textbox', { name: 'Equity' }).fill('40')
    await page.getByRole('textbox', { name: 'Range read' }).fill('60')
    await page.keyboard.press('Escape')
    await page.keyboard.press('b')
    await page.keyboard.press('1')
    await page.keyboard.press('v')
    await expect(page.getByRole('group', { name: 'Size' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Value', exact: false })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await page.waitForTimeout(400) // the size row slides in
    // the size row is one line (a wrapped row would cost another 48 px)
    const chips = await page.getByRole('group', { name: 'Size' }).getByRole('button').all()
    const tops = new Set<number>()
    for (const chip of chips) tops.add(Math.round((await chip.boundingBox())!.y))
    expect(tops.size).toBe(1)
    await expectFits(page, width, height, 'Bet, size, intent')

    await page.getByRole('button', { name: /^Submit/ }).click()
    await expect(page.getByRole('alert')).toContainText('Villain model changed')
    await expectFits(page, width, height, 'with the 409 error', { withError: true })
  })

  test(`layout: a river puzzle and an action without sizes fit ${width}×${height}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height })
    await routePuzzle(page, 'puzzle_river')
    await page.goto('/')
    await expect(page.getByRole('textbox', { name: 'Equity' })).toBeVisible()
    // the river's one-pixel overflow is gone
    await expectFits(page, width, height, 'river, fresh')

    await page.getByRole('textbox', { name: 'Equity' }).fill('40')
    await page.keyboard.press('Escape')
    const passive = page
      .locator('[aria-label="Action"] button:is([data-kind="check"], [data-kind="call"])')
      .and(page.locator(':not([aria-disabled])'))
      .first()
    await passive.click()
    await expect(passive).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('group', { name: 'Size' })).toHaveCount(0)
    await expectFits(page, width, height, 'river, an action without sizes')
  })

  test(`layout: pre-flop fits ${width}×${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    await routePuzzle(page, 'puzzle_preflop_btn_first_in')
    await page.goto('/')
    await expect(page.getByRole('textbox', { name: 'Equity' })).toBeVisible()
    await expectFits(page, width, height, 'pre-flop, fresh')
  })
}

for (const [width, height] of FIT_SIZES) {
  test(`layout: the Action panel ends with the table column at ${width}×${height}, and a long history scrolls inside it`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height })
    // a river puzzle with 40 extra river entries: far more history than the panel is tall
    const view = JSON.parse(fixtureJson('puzzle_river')) as { history: Record<string, unknown>[] }
    const base = view.history.at(-1)!
    for (let i = 0; i < 40; i++) {
      view.history.push({ ...base, actor: i % 2 === 0 ? 'villain' : 'hero', street: 'river' })
    }
    await page.route('**/api/puzzles/current', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(view) }),
    )
    await page.goto('/')
    await expect(page.getByRole('textbox', { name: 'Equity' })).toBeVisible()
    const columns = await page.evaluate(() => {
      const side = document.querySelector('aside')!
      // the column with the table and the answer panel
      const top = document.querySelector('section[aria-label="Poker table"]')!.parentElement!
      return {
        sideBottom: side.getBoundingClientRect().bottom,
        topBottom: top.getBoundingClientRect().bottom,
        sideScroll: side.scrollHeight - side.clientHeight,
        pageScroll: document.documentElement.scrollHeight - window.innerHeight,
      }
    })
    expect(Math.abs(columns.sideBottom - columns.topBottom)).toBeLessThanOrEqual(1)
    expect(columns.sideScroll).toBeGreaterThan(0)
    expect(columns.pageScroll).toBeLessThanOrEqual(0)
  })
}

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
  // the rewrite is held until the pending line has been seen, then released
  let release: () => void = () => {}
  const gate = new Promise<void>((r) => {
    release = r
  })
  // explanation_llm.json is attempt_bet's explanation (another spot than the puzzle on screen):
  // the test checks the Why tab's states, not that the text matches this puzzle
  await page.route('**/api/attempts/*/explanation', async (route) => {
    await gate
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
  release()
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

    // the six stat tiles: 3 columns by 2 rows
    const boxes = await page.locator('[data-testid^="tile-"]').evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect()
        return { x: Math.round(r.left), y: Math.round(r.top) }
      }),
    )
    expect(boxes).toHaveLength(6)
    expect(new Set(boxes.map((b) => b.x)).size).toBe(3)
    expect(new Set(boxes.map((b) => b.y)).size).toBe(2)
    expect(boxes[0]!.y).toBe(boxes[2]!.y)
    expect(boxes[3]!.y).toBe(boxes[5]!.y)
    expect(boxes[3]!.y).toBeGreaterThan(boxes[0]!.y)

    // the tooltip sits 10 px above the hovered point, with "Show data" open below the chart too
    const figure = page
      .locator('figure')
      .filter({ has: page.getByTestId('line-chart') })
      .first()
    await figure.getByText('Show data').click()
    await expect(figure.getByRole('table')).toBeVisible()
    const svg = figure.getByTestId('line-chart')
    const svgBox = (await svg.boundingBox())!
    await page.mouse.move(svgBox.x + svgBox.width * 0.4, svgBox.y + svgBox.height / 2)
    const tip = figure.getByTestId('chart-tooltip')
    await expect(tip).toBeVisible()
    const dot = (await svg.getByTestId('hover-dot').boundingBox())!
    const tipBox = (await tip.boundingBox())!
    const gap = dot.y + dot.height / 2 - (tipBox.y + tipBox.height)
    expect(gap).toBeGreaterThanOrEqual(8)
    expect(gap).toBeLessThanOrEqual(12)
  })
}

// One row means nothing overflows the bar and every control's box lies inside the bar and the
// viewport. CI's Linux runner falls back to a wider font than most desktops; DejaVu Sans stands in
// for it (where it isn't installed the browser uses its default and the check still holds).
for (const [width, height] of [
  [1024, 768],
  [1280, 800],
] as const) {
  for (const [name, path] of [
    ['Puzzles', '/'],
    ['Play', '/play'],
    ['Progress', '/progress'],
    ['Settings', '/settings'],
  ] as const) {
    test(`layout: the top bar is one row on ${name} at ${width}×${height} with a wide fallback font`, async ({
      page,
      request,
    }) => {
      // Play with a session open carries the bar's longest content: the tally and End session
      if (name === 'Play') expect((await request.post('/api/play/sessions')).ok()).toBe(true)
      try {
        await page.setViewportSize({ width, height })
        await page.goto(path)
        await page.addStyleTag({
          content:
            'body, button, select, input { font-family: "DejaVu Sans", sans-serif !important; }',
        })
        const header = page.getByRole('banner')
        await expect(header.getByRole('link', { name: 'Settings' })).toBeVisible()
        if (name === 'Puzzles') {
          await expect(header.getByRole('button', { name: /New puzzle/ })).toBeVisible()
        }
        if (name === 'Play') {
          await expect(header.getByRole('button', { name: 'End session' })).toBeVisible()
        }
        const bar = (await header.boundingBox())!
        const overflow = await header.evaluate((el) => el.scrollWidth - el.clientWidth)
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
        const fit = { overflow, outside }
        expect(fit.overflow).toBeLessThanOrEqual(0)
        expect(fit.outside).toEqual([])
      } finally {
        if (name === 'Play') {
          const current = await request.get('/api/play/sessions/current')
          if (current.ok()) {
            const { id } = (await current.json()) as { id: number }
            await request.post(`/api/play/sessions/${id}/end`)
          }
        }
      }
    })
  }
}

test('a Settings round trip: Pot odds off survives navigation and a reload, and is restored', async ({
  page,
  request,
}) => {
  const fixtureText = (name: string) =>
    readFileSync(resolve(import.meta.dirname, `../src/test/fixtures/${name}.json`), 'utf8')
  // a puzzle that faces a bet, so the table has a pot-odds line to hide
  await page.route('**/api/puzzles/current', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: fixtureText('puzzle_facing_all_in'),
    }),
  )
  try {
    await page.goto('/')
    await expect(page.getByText(/Pot odds: call needs/)).toBeVisible()
    await page.getByRole('link', { name: 'Settings' }).click()
    await page.getByRole('switch', { name: /Pot odds/ }).click()
    await expect(page.getByRole('switch', { name: /Pot odds/ })).toHaveAttribute(
      'aria-checked',
      'false',
    )
    await page.getByRole('link', { name: 'Puzzles' }).click()
    await expect(page.getByRole('textbox', { name: 'Equity' })).toBeVisible()
    await expect(page.getByText(/Pot odds: call needs/)).toHaveCount(0)
    await page.reload()
    await expect(page.getByRole('textbox', { name: 'Equity' })).toBeVisible()
    await expect(page.getByText(/Pot odds: call needs/)).toHaveCount(0)
  } finally {
    // the database is shared across tests
    await request.patch('/api/settings', { data: { show_pot_odds: true } })
  }
})

for (const [width, height] of FIT_SIZES) {
  test(`results: the Action panel never covers the details, and no tab scrolls sideways at ${width}×${height}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height })
    await page.goto('/')
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

    const noSideScroll = async (tab: string) => {
      const over = await page.evaluate(() => {
        const html = document.documentElement
        const panel = document.querySelector('[role="tabpanel"]:not([hidden])')!
        return {
          page: html.scrollWidth - html.clientWidth,
          panel: panel.scrollWidth - panel.clientWidth,
        }
      })
      expect(over.page, `${tab}: page scrolls sideways`).toBeLessThanOrEqual(0)
      expect(over.panel, `${tab}: tab panel scrolls sideways`).toBeLessThanOrEqual(0)
    }
    for (const tab of ['Why', 'Options', 'Maths', 'Range', 'Hand']) {
      await page.getByRole('tab', { name: tab }).click()
      await noSideScroll(tab)
    }

    await page.getByRole('tab', { name: 'Maths' }).click()
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
    const boxes = await page.evaluate(() => {
      const rect = (el: Element) => el.getBoundingClientRect().toJSON()
      return {
        side: rect(document.querySelector('main:not([hidden]) aside')!),
        details: rect(document.querySelector('main:not([hidden]) section[aria-label="Details"]')!),
      }
    })
    const { side, details } = boxes
    const overlap =
      side.left < details.right &&
      details.left < side.right &&
      side.top < details.bottom &&
      details.top < side.bottom
    expect(overlap, 'the Action panel and the details overlap').toBe(false)
  })
}
