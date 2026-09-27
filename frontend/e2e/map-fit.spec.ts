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
