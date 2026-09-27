import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import type { Page } from '@playwright/test'
import { connectionPill, expect, headerClock, test } from './stub'

// Snapshots at three widths for six states. Baselines stay local (visual-baseline/, not committed):
// the first run writes them, later runs compare. Every run also saves its shots to test-results/visual/.
const WIDTHS = [375, 768, 1440]

interface VisualState {
  name: string
  url: string
  stub?: Record<string, string>
  setup: (page: Page) => Promise<void>
}

async function pausedAtStart(page: Page) {
  await expect(async () => {
    await page.getByRole('button', { name: 'Начать заново' }).click()
    await page.getByRole('button', { name: 'Пауза' }).click()
    expect(await headerClock(page)).toBe('12:40:00')
  }).toPass({ timeout: 10_000 })
}

const scenario = (value: string) => async (page: Page) => {
  await page.getByRole('combobox', { name: 'Сценарий' }).selectOption(value)
  if (value === 'normal' || value === 'many') await pausedAtStart(page)
}

const STATES: VisualState[] = [
  { name: 'demo-normal', url: '/?source=demo', setup: scenario('normal') },
  { name: 'demo-many', url: '/?source=demo', setup: scenario('many') },
  { name: 'demo-empty', url: '/?source=demo', setup: scenario('empty') },
  { name: 'demo-disconnected', url: '/?source=demo', setup: scenario('disconnected') },
  { name: 'live-status-skew', url: '/', stub: { STUB_CASE: 'status-skew' }, setup: (page) => expect(connectionPill(page, 'LIVE')).toBeVisible() },
  { name: 'live-no-backend', url: '/', setup: (page) => expect(connectionPill(page, 'НЕТ СВЯЗИ')).toBeVisible() },
]

for (const state of STATES) {
  for (const width of WIDTHS) {
    test(`${state.name} ${width}px`, async ({ page, stub }, testInfo) => {
      if (state.stub) await stub.start(state.stub)
      await page.setViewportSize({ width, height: 900 })
      await page.goto(state.url)
      await state.setup(page)
      await page.waitForTimeout(1_500)
      const name = `${state.name}-${width}.png`
      const shot = resolve('test-results', 'visual', name)
      mkdirSync(dirname(shot), { recursive: true })
      // The artifact shows the page as is; the comparison masks map tiles and the running clock,
      // which change between runs (the map canvas has no accessible name, so it is found by tag).
      await page.screenshot({ path: shot, fullPage: true, animations: 'disabled' })
      const options = {
        fullPage: true,
        animations: 'disabled' as const,
        mask: [page.locator('canvas'), page.getByRole('banner').getByText(/\d\d:\d\d:\d\d/)],
      }
      const baseline = testInfo.snapshotPath(name)
      if (!existsSync(baseline)) {
        mkdirSync(dirname(baseline), { recursive: true })
        writeFileSync(baseline, await page.screenshot(options))
        testInfo.annotations.push({ type: 'baseline', description: `created ${baseline}` })
        return
      }
      await expect(page).toHaveScreenshot(name, { ...options, maxDiffPixelRatio: 0.02 })
    })
  }
}
