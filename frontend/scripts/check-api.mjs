// Fails when src/api/schema.d.ts is not what openapi-typescript generates from openapi.json.
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { API_ARGS } from './api-args.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const cli = join(root, 'node_modules', 'openapi-typescript', 'bin', 'cli.js')
const tmp = mkdtempSync(join(tmpdir(), 'check-api-'))
const generated = join(tmp, 'schema.d.ts')

const normalise = (text) => text.replace(/\r\n/g, '\n')

try {
  const run = spawnSync(
    process.execPath,
    [cli, join(root, 'openapi.json'), '-o', generated, ...API_ARGS],
    {
      cwd: root,
      encoding: 'utf8',
    },
  )
  if (run.status !== 0) {
    process.stderr.write(run.stdout + run.stderr)
    process.exitCode = 1
  } else {
    const fresh = normalise(readFileSync(generated, 'utf8'))
    const committed = normalise(readFileSync(join(root, 'src', 'api', 'schema.d.ts'), 'utf8'))
    if (fresh !== committed) {
      console.error('src/api/schema.d.ts is stale: run `npm run gen:api` and commit the result.')
      process.exitCode = 1
    } else {
      console.log('src/api/schema.d.ts is up to date.')
    }
  }
} finally {
  rmSync(tmp, { recursive: true, force: true })
}
