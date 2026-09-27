import { spawn, type ChildProcess } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { expect, test as base, type Page } from '@playwright/test'

export const STUB_PORT = 8000
const script = fileURLToPath(new URL('../scripts/mock-backend.mjs', import.meta.url))

export interface Stub {
  start(env?: Record<string, string>): Promise<void>
  stop(): Promise<void>
}

async function healthy(): Promise<boolean> {
  try { return (await fetch(`http://127.0.0.1:${STUB_PORT}/health`)).ok } catch { return false }
}

/** The test stream from scripts/mock-backend.mjs on port 8000, where the Vite proxy expects the backend. */
function createStub(): Stub {
  let child: ChildProcess | null = null
  let lastEnv: Record<string, string> = {}
  const stop = async () => {
    const current = child
    child = null
    if (!current || current.exitCode != null) return
    const exited = new Promise((resolve) => current.once('exit', resolve))
    current.kill()
    await exited
  }
  return {
    async start(env = lastEnv) {
      await stop()
      if (await healthy()) throw new Error(`Port ${STUB_PORT} is busy: stop the backend or stub before running e2e`)
      lastEnv = env
      child = spawn(process.execPath, [script], { env: { ...process.env, STUB_PORT: String(STUB_PORT), ...env }, stdio: 'ignore' })
      await expect.poll(healthy, { timeout: 15_000, message: 'stub /health' }).toBe(true)
    },
    stop,
  }
}

export const test = base.extend<{ stub: Stub }>({
  stub: async ({}, use) => {
    const stub = createStub()
    await use(stub)
    await stub.stop()
  },
})

export { expect }

/** The clock in the header, HH:MM:SS of the stream or demo time. */
export async function headerClock(page: Page): Promise<string> {
  const text = await page.getByRole('banner').getByText(/\d\d:\d\d:\d\d/).textContent()
  return /\d\d:\d\d:\d\d/.exec(text ?? '')?.[0] ?? ''
}

export const connectionPill = (page: Page, text: string) => page.getByRole('banner').getByText(text, { exact: true })
