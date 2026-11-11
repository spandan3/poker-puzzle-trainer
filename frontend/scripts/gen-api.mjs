// Generates src/api/schema.d.ts from openapi.json.
import { spawnSync } from 'node:child_process'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { API_ARGS } from './api-args.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const cli = join(root, 'node_modules', 'openapi-typescript', 'bin', 'cli.js')
const run = spawnSync(
  process.execPath,
  [cli, join(root, 'openapi.json'), '-o', join(root, 'src', 'api', 'schema.d.ts'), ...API_ARGS],
  { cwd: root, stdio: 'inherit' },
)
process.exitCode = run.status ?? 1
