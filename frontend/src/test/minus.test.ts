// One minus sign: U+2212 is spelled only in lib/format.ts (`MINUS`); everything else imports it.
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = resolve(import.meta.dirname, '..')
const MINUS_SIGN = String.fromCharCode(0x2212)

/** every .ts / .tsx source under src/, without tests, test helpers or fixtures */
function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) {
      return entry.name === 'test' || entry.name === 'fixtures' ? [] : sources(path)
    }
    if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) return []
    return [path]
  })
}

describe('the minus sign', () => {
  it('is spelled only in lib/format.ts', () => {
    const files = sources(SRC)
    expect(files.length).toBeGreaterThan(50)
    const offenders = files
      .filter((f) => readFileSync(f, 'utf8').includes(MINUS_SIGN))
      .map((f) => relative(SRC, f).split(sep).join('/'))
    expect(offenders).toEqual([])
  })
})
