// WCAG 2.1 contrast, for checking the colour claims the design tokens make. Used by tests.

export interface Rgb {
  r: number
  g: number
  b: number
}

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i
const FUNC = /^rgba?\(\s*([^)]*?)\s*\)$/i

function channel(text: string): number {
  const t = text.trim()
  const n = t.endsWith('%') ? (parseFloat(t) / 100) * 255 : parseFloat(t)
  if (!Number.isFinite(n)) throw new Error(`bad colour channel: ${text}`)
  return Math.round(Math.min(255, Math.max(0, n)))
}

/** Reads `#rgb`, `#rrggbb`, and `rgb(r g b / a%)` or `rgb(r, g, b)`. Alpha is returned apart. */
export function parseColor(input: string): Rgb & { a: number } {
  const s = input.trim()
  const hex = HEX.exec(s)
  if (hex) {
    let h = hex[1] as string
    if (h.length === 3) h = [...h].map((c) => c + c).join('')
    return {
      r: parseInt(h.slice(0, 2), 16),
      g: parseInt(h.slice(2, 4), 16),
      b: parseInt(h.slice(4, 6), 16),
      a: 1,
    }
  }
  const fn = FUNC.exec(s)
  if (fn) {
    const [colour = '', alphaPart] = (fn[1] as string).split('/')
    let parts = colour.includes(',') ? colour.split(',') : colour.trim().split(/\s+/)
    let alpha = alphaPart
    if (alpha === undefined && parts.length === 4) {
      alpha = parts[3]
      parts = parts.slice(0, 3)
    }
    if (parts.length !== 3) throw new Error(`cannot parse colour: ${input}`)
    let a = 1
    if (alpha !== undefined) {
      const t = alpha.trim()
      a = t.endsWith('%') ? parseFloat(t) / 100 : parseFloat(t)
      if (!Number.isFinite(a)) throw new Error(`bad alpha in colour: ${input}`)
    }
    const [r, g, b] = parts.map(channel) as [number, number, number]
    return { r, g, b, a }
  }
  throw new Error(`cannot parse colour: ${input}`)
}

const DECL = /(--[\w-]+)\s*:\s*([^;]+);/g
const VAR = /^var\(\s*(--[\w-]+)\s*\)$/

/**
 * The custom properties declared in the `:root` blocks of the given CSS texts, with `var(--x)`
 * aliases resolved. Reading a gradient token (or an alias of one) throws an error that names it,
 * so a gradient can't be mistaken for a colour.
 */
export function resolveTokens(cssTexts: string[]): Record<string, string> {
  const raw: Record<string, string> = {}
  for (const text of cssTexts) {
    const noComments = text.replace(/\/\*[\s\S]*?\*\//g, '')
    for (const m of noComments.matchAll(DECL)) {
      raw[m[1] as string] = (m[2] as string).trim().replace(/\s+/g, ' ')
    }
  }
  const resolve = (name: string, seen: string[]): string => {
    if (seen.includes(name)) throw new Error(`token cycle: ${[...seen, name].join(' -> ')}`)
    const value = raw[name]
    if (value === undefined) throw new Error(`unknown token ${name}`)
    if (/gradient\(/.test(value)) throw new Error(`token ${name} is a gradient, not a colour`)
    const alias = VAR.exec(value)
    return alias ? resolve(alias[1] as string, [...seen, name]) : value
  }
  const out: Record<string, string> = {}
  for (const name of Object.keys(raw)) {
    Object.defineProperty(out, name, {
      enumerable: true,
      get: () => resolve(name, []),
    })
  }
  return out
}

/** `fg` at `alpha` laid over the opaque `bg`. */
export function composite(fg: string, alpha: number, bg: string): string {
  const f = parseColor(fg)
  const b = parseColor(bg)
  const mix = (x: number, y: number) => Math.round(x * alpha + y * (1 - alpha))
  const hex = (n: number) => n.toString(16).padStart(2, '0')
  return `#${hex(mix(f.r, b.r))}${hex(mix(f.g, b.g))}${hex(mix(f.b, b.b))}`
}

function luminance(colour: string): number {
  const { r, g, b } = parseColor(colour)
  const lin = (v: number) => {
    const s = v / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

/** WCAG 2.1 contrast ratio (1 to 21) of two opaque colours. */
export function contrastRatio(a: string, b: string): number {
  const la = luminance(a)
  const lb = luminance(b)
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}
