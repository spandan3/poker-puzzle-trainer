import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

// Every font size in a CSS module is a token, so the 11 px text floor (--text-min) holds and the
// type scale lives in one place. Three forms are allowed:
//   var(--text-…)                      the type scale
//   max(<n>em, var(--text-min))        text on the table: scales with the table, never under the floor
//   anything in Card.module.css        the rank and suit drawn on a card (the one exemption)
// plus the table's own base size, whose clamp is bounded by the table-font tokens.
const SRC = resolve(import.meta.dirname, '..')

function modules(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name)
    if (e.isDirectory()) return modules(p)
    return e.name.endsWith('.css') ? [p] : []
  })
}

const TOKEN = /^var\(--text-[a-z0-9-]+\)$/
const TABLE_TEXT = /^max\(\d*\.?\d+em, var\(--text-min\)\)$/
const TABLE_BASE =
  /^clamp\(var\(--table-font-min\), var\(--table-font-fluid\), var\(--table-font-max\)\)$/

describe('font sizes', () => {
  const files = modules(SRC).filter((f) => !f.endsWith('tokens.css'))

  it('finds the CSS modules', () => {
    expect(files.length).toBeGreaterThan(20)
  })

  it('every font-size is a token, a floored table size, or a card face', () => {
    const bad: string[] = []
    for (const file of files) {
      const rel = relative(SRC, file).replaceAll('\\', '/')
      const text = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
      for (const m of text.matchAll(/(?<![-\w])font-size:\s*([^;]+);/g)) {
        const value = m[1]!.trim()
        if (TOKEN.test(value) || TABLE_TEXT.test(value)) continue
        if (rel === 'components/Table/Table.module.css' && TABLE_BASE.test(value)) continue
        if (rel === 'components/Card/Card.module.css') continue
        bad.push(`${rel}: font-size: ${value}`)
      }
      // the `font` shorthand would hide a size
      for (const m of text.matchAll(/(?<![-\w])font:\s*([^;]+);/g)) {
        if (m[1]!.trim() !== 'inherit') bad.push(`${rel}: font: ${m[1]!.trim()}`)
      }
    }
    expect(bad).toEqual([])
  })
})

// The spacing rule: --section-gap between a page's sections, --panel-pad inside a Panel. Each page
// root and the Panel primitive must say so by token (a raw --space-… would let them drift apart).
describe('spacing', () => {
  const rule = (file: string, selector: string): string => {
    const text = readFileSync(join(SRC, file), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
    const m = text.match(new RegExp(`(?:^|\\n)${selector.replace('.', '\\.')} \\{([^}]*)\\}`))
    if (!m) throw new Error(`no ${selector} in ${file}`)
    return m[1]!
  }
  const gap = (body: string) => body.match(/(?<![-\w])gap:\s*([^;]+);/)?.[1]?.trim()

  it.each([
    ['components/Settings/Settings.module.css', '.page'],
    ['components/Progress/Progress.module.css', '.page'],
    ['components/Play/HandAnalysis.module.css', '.root'],
  ])('%s %s: sections are --section-gap apart', (file, selector) => {
    expect(gap(rule(file, selector))).toBe('var(--section-gap)')
  })

  it('the table screens: the top row and the results details are --section-gap apart', () => {
    expect(gap(rule('styles/tableLayout.module.css', '.main'))).toMatch(/^var\(--section-gap\) /)
  })

  it('a Panel pads its header and body with --panel-pad', () => {
    const css = 'components/ui/ui.module.css'
    expect(rule(css, '.panelBody')).toMatch(/padding: var\(--panel-pad\);/)
    expect(rule(css, '.panelHeader')).toMatch(/padding: var\(--panel-pad\) var\(--panel-pad\) 0;/)
  })
})
