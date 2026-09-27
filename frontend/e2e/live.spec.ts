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
    await page.getByRole('complementary', { name: 'Лента предупреждений' }).getByRole('button', { name: /^Событие .*борт 131672/ }).click()
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
    await expect(page.getByText('Живой поток недоступен. Повторное подключение выполняется автоматически.')).toHaveCount(0)
  })

  test('регрессия P0-1 (status-skew): кадры принимаются, часы идут, счётчики заполнены', async ({ page, stub }) => {
    await stub.start({ STUB_CASE: 'status-skew' })
    await page.goto('/')
    await expect(connectionPill(page, 'LIVE')).toBeVisible()
    const summary = page.getByRole('region', { name: 'Состояние движения' })
    await expect(summary).toContainText(/3\s*в потоке/)
    await expect(summary).toContainText(/\d+\s*алертов/)
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
    await expect(page.getByRole('region', { name: 'Управление источником данных' }).getByText('Поток подключён')).toBeVisible()
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
  test.fixme('S1: на 1440×900 без прокрутки видны карта, ≥ 5 карточек ленты и карточка инцидента', async () => {
    // По аудиту (раздел 7) первый экран занят шапкой и сводкой, Марей ниже сгиба; раскладку меняет этап 3 (BL-15, BL-16).
  })

  test.fixme('S5: подписи диаграммы Марея не меньше 11 px', async () => {
    // По аудиту подписи диаграммы 7–9 px; кегли меняет этап 3 (BL-22).
  })
})
