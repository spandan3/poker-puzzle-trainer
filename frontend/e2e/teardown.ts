import { rmSync } from 'node:fs'

// Removes the run's temporary database (playwright.config.ts sets PPT_E2E_DB).
export default function teardown(): void {
  const db = process.env.PPT_E2E_DB
  if (!db) return
  try {
    rmSync(db, { force: true })
  } catch {
    // the server may still hold it open on Windows; the OS temp dir is cleaned eventually
  }
}
