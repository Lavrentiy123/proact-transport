import { connectionPill, expect, headerClock, test } from './stub'

const card = (page: import('@playwright/test').Page) => page.getByRole('complementary', { name: 'Карточка выбранного борта' })
const vehiclePicker = (page: import('@playwright/test').Page) => page.getByRole('combobox', { name: 'Выбрать борт на карте' })

test.describe('живой поток на stub', () => {
  test('S2: выбор борта в списке «Борт» и в ленте показывает рекомендацию', async ({ page, stub }) => {
    await stub.start()
    await page.goto('/')
    await expect(connectionPill(page, 'LIVE')).toBeVisible()

    await vehiclePicker(page).selectOption('122658')
    await expect(card(page).getByRole('heading', { name: 'Борт 122658' })).toBeVisible()
    await expect(card(page).getByText('Рекомендация диспетчеру')).toHaveCount(0)

    await vehiclePicker(page).selectOption('131672')
    await expect(card(page).getByRole('heading', { name: 'Борт 131672' })).toBeVisible()
    await expect(card(page).getByText('Рекомендация диспетчеру')).toBeVisible()
    await expect(card(page).getByRole('button', { name: 'Отправить водителю' })).toBeVisible()

    await vehiclePicker(page).selectOption('130072')
    await page.getByRole('complementary', { name: 'Лента предупреждений' }).getByRole('button', { name: /^Борт 131672,/ }).click()
    await expect(card(page).getByRole('heading', { name: 'Борт 131672' })).toBeVisible()
    await expect(card(page).getByText('Рекомендация диспетчеру')).toBeVisible()
  })

  test('S3: «Отправить водителю» → отправка → ответ водителя', async ({ page, stub }) => {
    await stub.start()
    // Hold the answer for a moment so the pending state can be observed.
    await page.route('**/api/v1/actions', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1_000))
      await route.continue()
    })
    await page.goto('/')
    await expect(connectionPill(page, 'LIVE')).toBeVisible()
    await vehiclePicker(page).selectOption('131672')
    await card(page).getByRole('button', { name: 'Отправить водителю' }).click()
    await expect(card(page).getByRole('button', { name: 'Отправка…' })).toBeDisabled()
    await expect(card(page).getByText('Отправлено водителю')).toBeVisible()
    await expect(card(page).getByText('Ответ водителя: «успеваю»')).toBeVisible()
  })

  test('S4: обрыв потока → «НЕТ СВЯЗИ», восстановление → «LIVE»', async ({ page, stub }) => {
    await stub.start()
    await page.goto('/')
    await expect(connectionPill(page, 'LIVE')).toBeVisible()
    await stub.stop()
    await expect(connectionPill(page, 'НЕТ СВЯЗИ')).toBeVisible()
    await expect(page.getByText('Живой поток недоступен. Повторное подключение выполняется автоматически.')).toBeVisible()
    await expect(page.getByRole('region', { name: 'Состояние движения' }).getByText('в последнем снимке')).toBeVisible()
    await stub.start()
    await expect(connectionPill(page, 'LIVE')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(/^Связь восстановлена в \d\d:\d\d:\d\d$/)).toBeVisible()
    await expect(page.getByText('Живой поток недоступен. Повторное подключение выполняется автоматически.')).toHaveCount(0)
  })

  test('регрессия P0-1 (status-skew): кадры принимаются, часы идут, счётчики заполнены', async ({ page, stub }) => {
    await stub.start({ STUB_CASE: 'status-skew' })
    await page.goto('/')
    await expect(connectionPill(page, 'LIVE')).toBeVisible()
    const summary = page.getByRole('region', { name: 'Состояние движения' })
    await expect(summary).toContainText(/3\s*в потоке/)
    await expect(summary).toContainText(/\d+\s*предупрежд/)
    const first = await headerClock(page)
    await expect.poll(() => headerClock(page), { timeout: 10_000 }).not.toBe(first)
  })

  test('регрессия P0-2 (rewind): перемотка назад — новый сеанс без баннера застоя', async ({ page, stub }) => {
    await stub.start({ STUB_CASE: 'rewind' })
    await page.goto('/')
    await expect(connectionPill(page, 'LIVE')).toBeVisible()
    const before = await headerClock(page)
    await expect.poll(async () => (await headerClock(page)).slice(0, 2), { timeout: 20_000 }).not.toBe(before.slice(0, 2))
    const rewound = await headerClock(page)
    expect(rewound < before).toBe(true)
    // Longer than the 15 s stall threshold after the rewind.
    await page.waitForTimeout(17_000)
    await expect(page.getByText('Данные о бортах не обновляются более 15 секунд. Показан последний снимок.')).toHaveCount(0)
    await expect(connectionPill(page, 'LIVE')).toBeVisible()
    expect(await headerClock(page) > rewound).toBe(true)
  })

  test('регрессия D11 (drop-selected): выбранный диспетчером борт пропал → «Выберите борт»', async ({ page, stub }) => {
    await stub.start({ STUB_CASE: 'drop-selected' })
    await page.goto('/')
    await expect(connectionPill(page, 'LIVE')).toBeVisible()
    await vehiclePicker(page).selectOption('131672')
    await expect(card(page).getByRole('heading', { name: 'Борт 131672' })).toBeVisible()
    await expect(page.getByText('Выберите борт', { exact: true })).toBeVisible({ timeout: 15_000 })
    await expect(vehiclePicker(page).locator('option', { hasText: '131672' })).toHaveCount(0)
  })

  test('BL-32: повреждённый кадр учтён в «Диагностике», поток продолжается', async ({ page, stub }) => {
    await stub.start({ STUB_CASE: 'bad-frame' })
    await page.goto('/')
    await expect(connectionPill(page, 'LIVE')).toBeVisible()
    const toolbar = page.getByRole('region', { name: 'Управление источником данных' })
    await toolbar.getByText('Диагностика').click()
    await expect(toolbar.getByText(/^Отброшено кадров: [1-9]/)).toBeVisible({ timeout: 10_000 })
    await expect(toolbar.getByText('Последняя причина отказа: повреждённый JSON')).toBeVisible()
    await expect(connectionPill(page, 'LIVE')).toBeVisible()
  })
})

test.describe('цели этапа 3', () => {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1366, height: 768 }]) {
    test(`S1: на ${viewport.width}×${viewport.height} без прокрутки видны карта, ≥ 5 карточек ленты, карточка инцидента и Марей`, async ({ page }) => {
      await page.setViewportSize(viewport)
      await page.goto('/?source=demo')
      await page.getByRole('combobox', { name: 'Сценарий' }).selectOption('many')
      const feed = page.getByRole('complementary', { name: 'Лента предупреждений' })
      await expect(feed.getByRole('button', { name: /^Борт / }).nth(6)).toBeVisible()
      await page.getByRole('button', { name: 'Пауза' }).click()
      type Box = { x: number, y: number, width: number, height: number }
      const screen: Box = { x: 0, y: 0, ...viewport }
      const within = async (locator: import('@playwright/test').Locator, area: Box = screen) => {
        const box = await locator.boundingBox()
        return box != null && box.y >= area.y - 0.5 && box.x >= area.x - 0.5 && box.y + box.height <= area.y + area.height + 0.5 && box.x + box.width <= area.x + area.width + 0.5 &&
          box.y + box.height <= viewport.height + 0.5
      }
      const page_ = await page.evaluate(() => ({ h: document.documentElement.scrollHeight, w: document.documentElement.scrollWidth }))
      expect(page_.h).toBeLessThanOrEqual(viewport.height)
      expect(page_.w).toBeLessThanOrEqual(viewport.width)
      expect((await page.getByRole('banner').boundingBox())!.height).toBeLessThanOrEqual(56)
      expect(await within(page.locator('section.map-panel'))).toBe(true)
      const feedArea = (await feed.locator('.alerts-scroll').boundingBox())!
      const items = feed.locator('.alert-item')
      let fullyVisible = 0
      for (let index = 0; index < await items.count(); index += 1) if (await within(items.nth(index), feedArea)) fullyVisible += 1
      expect(fullyVisible).toBeGreaterThanOrEqual(5)
      const incident = card(page)
      const cardArea = (await incident.boundingBox())!
      expect(await within(incident.locator('.incident-risk-band'), cardArea)).toBe(true)
      expect(await within(incident.locator('.recommendation-box'), cardArea)).toBe(true)
      expect(await within(incident.getByRole('button', { name: 'Отправить водителю' }), cardArea)).toBe(true)
      expect(await within(incident.locator('.cause-section strong'), cardArea)).toBe(true)
      const marey = (await page.locator('.marey-band').boundingBox())!
      expect(marey.height).toBeGreaterThanOrEqual(120)
      expect(marey.y + 120).toBeLessThanOrEqual(viewport.height)
    })
  }

  for (const [width, height] of [[1440, 900], [768, 1024], [375, 812]] as const) {
    test(`S5: подписи диаграммы Марея не меньше 11 px на ${width} px`, async ({ page, stub }) => {
      await page.setViewportSize({ width, height })
      await stub.start()
      await page.goto('/')
      await expect(connectionPill(page, 'LIVE')).toBeVisible()
      await vehiclePicker(page).selectOption('131672')
      const chart = page.getByRole('region', { name: 'Диаграмма движения борта 131672' }).getByRole('img', { name: 'Линия плана, наблюдения и диапазон прогноза' })
      await expect(chart).toBeVisible()
      const metrics = await chart.evaluate((svg) => {
        const scale = svg.getBoundingClientRect().width / (svg as SVGSVGElement).viewBox.baseVal.width
        const sizes = [...svg.querySelectorAll('text')].map((text) => Number.parseFloat(getComputedStyle(text).fontSize) * scale)
        const box = svg.getBoundingClientRect()
        const clipped = [...svg.querySelectorAll('text')].filter((text) => {
          const rect = text.getBoundingClientRect()
          return rect.top < box.top - 1 || rect.bottom > box.bottom + 1 || rect.left < box.left - 1 || rect.right > box.right + 1
        }).map((text) => text.textContent)
        return { count: sizes.length, min: Math.min(...sizes), max: Math.max(...sizes), clipped,
          overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth }
      })
      expect(metrics.count).toBeGreaterThan(3)
      expect(metrics.min).toBeGreaterThanOrEqual(11)
      expect(metrics.max).toBeLessThanOrEqual(12.5)
      expect(metrics.clipped).toEqual([])
      expect(metrics.overflow).toBeLessThanOrEqual(0)
    })
  }
})
