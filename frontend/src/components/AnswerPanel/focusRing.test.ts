import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(resolve(import.meta.dirname, 'AnswerPanel.module.css'), 'utf8')

// jsdom has no cascade for CSS modules, so the rule text is what we can pin; the e2e test checks
// the computed style in a real browser.
describe('AnswerPanel focus ring on selected buttons', () => {
  it('keeps the focus ring on a selected action, size and intent', () => {
    expect(css).toMatch(
      /\.action\[aria-pressed='true'\]:focus-visible\s*\{[^}]*var\(--focus-ring\)/,
    )
    expect(css).toMatch(
      /:is\(\.size, \.intentButton\)\[aria-pressed='true'\]:focus-visible\s*\{[^}]*var\(--focus-ring\)/,
    )
  })
})
