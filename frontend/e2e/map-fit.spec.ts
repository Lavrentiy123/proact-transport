import type { Page } from '@playwright/test'
import { connectionPill, expect, test } from './stub'

// The first view, without any clicks, must frame every vehicle that has a valid position.
const viewports = [
  { width: 1440, height: 900 },
  { width: 1366, height: 768 },
  { width: 768, height: 1024 },
  { width: 375, height: 812 },
]

async function expectAllInView(page: Page, onMap: number) {
  await expect(page.locator('.map-count')).toContainText(`${onMap} на карте`)
  await expect(page.locator('section.map-panel')).toHaveAttribute('data-in-view', String(onMap))
}

for (const viewport of viewports) {
  test(`начальный обзор карты на ${viewport.width}×${viewport.height}: live, 100 бортов — в кадре все 95 с позицией`, async ({ page, stub }) => {
    await page.setViewportSize(viewport)
    await stub.start({ STUB_VEHICLES: '100' })
    await page.goto('/')
    await expect(connectionPill(page, 'LIVE')).toBeVisible()
    await expectAllInView(page, 95)
  })

  test(`начальный обзор карты на ${viewport.width}×${viewport.height}: демо — в кадре все борта`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.goto('/?source=demo')
    await expect(connectionPill(page, 'REPLAY')).toBeVisible()
    const onMap = Number((await page.locator('.map-count').textContent())?.match(/(\d+) на карте/)?.[1])
    expect(onMap).toBeGreaterThan(0)
    await expectAllInView(page, onMap)
  })
}

// A hidden tab does not render, so it requests no tiles: the basemap wait must not run out
// until the page is shown, otherwise the map opens on the schematic.
test('скрытая вкладка не переключает подложку на схему, пока страница не показана', async ({ page }) => {
  test.setTimeout(45_000)
  await page.addInitScript(() => {
    let hidden = true
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (hidden ? 'hidden' : 'visible') })
    ;(window as unknown as { showPage: () => void }).showPage = () => {
      hidden = false
      document.dispatchEvent(new Event('visibilitychange'))
    }
  })
  await page.route(/tiles\.openfreemap\.org/, () => {})
  await page.goto('/?source=demo')
  await expect(connectionPill(page, 'REPLAY')).toBeVisible()
  await page.waitForTimeout(9_000)
  await expect(page.locator('.map-basemap-status')).toHaveCount(0)
  await page.evaluate(() => (window as unknown as { showPage: () => void }).showPage())
  await expect(page.locator('.map-basemap-status')).toHaveText('Схема без карты', { timeout: 12_000 })
})
