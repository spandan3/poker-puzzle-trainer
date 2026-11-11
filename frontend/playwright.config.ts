import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const port = process.env.PPT_E2E_PORT ?? '8765'
// One file per run (the pid), removed by e2e/teardown.ts; the path reaches it through the env.
const dbFile = process.env.PPT_E2E_DB ?? join(tmpdir(), `ppt-e2e-${process.pid}.db`)
process.env.PPT_E2E_DB = dbFile
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE

export default defineConfig({
  testDir: './e2e',
  globalTeardown: './e2e/teardown.ts',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 800 },
        launchOptions: executablePath ? { executablePath } : {},
      },
    },
  ],
  webServer: {
    command: 'uv run --project ../backend serve',
    url: `http://127.0.0.1:${port}/api/health`,
    env: {
      PPT_PORT: port,
      PPT_DATABASE_URL: `sqlite:///${dbFile.replaceAll('\\', '/')}`,
      PPT_FRONTEND_DIST: resolve(import.meta.dirname, 'dist'),
    },
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
