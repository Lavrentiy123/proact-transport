import type { Page } from '@playwright/test'
import { connectionPill, expect, test } from './stub'

// The remaining STUB_CASE injections of frontend/README.md, so stage 1 behaviour stays pinned.
const routeBanner = 'Маршрут выбранного борта недоступен. Положение и прогноз из потока продолжают отображаться.'
const marey = (page: Page, trId: number) => page.getByRole('region', { name: `Диаграмма движения борта ${trId}` })
const vehiclePicker = (page: Page) => page.getByRole('combobox', { name: 'Выбрать борт на карте' })

test('slow-first: без снимка 5 с — «Вернуться в демо», затем поток', async ({ page, stub }) => {
  await stub.start({ STUB_CASE: 'slow-first', STUB_TRIGGER_TICK: '9' })
  await page.goto('/')
  await expect(connectionPill(page, 'ОЖИДАНИЕ ДАННЫХ')).toBeVisible()
  await expect(page.getByText('Соединение установлено. Ожидаем новый снимок с положением бортов.')).toBeVisible()
  await expect(page.getByText('Данные о бортах не поступают. Проверьте источник или вернитесь в демо.')).toBeVisible({ timeout: 8_000 })
  await expect(page.getByRole('button', { name: 'Вернуться в демо' })).toBeVisible()
  await expect(connectionPill(page, 'LIVE')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('button', { name: 'Вернуться в демо' })).toHaveCount(0)
})

test('partial-both: отдельные кадры alert и status не сбивают поток', async ({ page, stub }) => {
  await stub.start({ STUB_CASE: 'partial-both' })
  await page.goto('/')
  await expect(connectionPill(page, 'LIVE')).toBeVisible()
  await page.waitForTimeout(5_000)
  await expect(connectionPill(page, 'LIVE')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Состояние движения' })).toContainText(/1\s*предупреждение(?!й)/)
  await page.getByRole('region', { name: 'Управление источником данных' }).getByText('Диагностика').click()
  await expect(page.getByText('Отброшено кадров: 0')).toBeVisible()
})

test('track-500: ошибка маршрута показана, положение и прогноз остаются', async ({ page, stub }) => {
  await stub.start({ STUB_CASE: 'track-500' })
  await page.goto('/')
  await expect(connectionPill(page, 'LIVE')).toBeVisible()
  await vehiclePicker(page).selectOption('131672')
  await expect(page.getByText(routeBanner)).toBeVisible()
  await expect(page.getByText('Маршрут недоступен; положение и прогноз сохранены')).toBeVisible()
  await expect(page.getByRole('complementary', { name: 'Карточка выбранного борта' }).getByText('Рекомендация диспетчеру')).toBeVisible()
})

test('track-timeout: маршрут без ответа 8 с считается недоступным', async ({ page, stub }) => {
  await stub.start({ STUB_CASE: 'track-timeout' })
  await page.goto('/')
  await expect(connectionPill(page, 'LIVE')).toBeVisible()
  await vehiclePicker(page).selectOption('131672')
  await expect(page.getByText('Загрузка маршрута…')).toBeVisible()
  await expect(page.getByText(routeBanner)).toBeVisible({ timeout: 12_000 })
})

test('track-race: поздний ответ по прошлому борту не перекрывает новый выбор', async ({ page, stub }) => {
  await stub.start({ STUB_CASE: 'track-race' })
  await page.goto('/')
  await expect(connectionPill(page, 'LIVE')).toBeVisible()
  await vehiclePicker(page).selectOption('131672')
  await vehiclePicker(page).selectOption('122658')
  await expect(marey(page, 122658)).toBeVisible()
  // The delayed answer for 131672 arrives after 3.5 s.
  await page.waitForTimeout(4_500)
  await expect(marey(page, 122658)).toBeVisible()
  await expect(marey(page, 131672)).toHaveCount(0)
  await expect(page.getByText(routeBanner)).toHaveCount(0)
})

test('long-track: 35 остановок строят диаграмму', async ({ page, stub }) => {
  await stub.start({ STUB_CASE: 'long-track' })
  await page.goto('/')
  await expect(connectionPill(page, 'LIVE')).toBeVisible()
  await vehiclePicker(page).selectOption('131672')
  await expect(marey(page, 131672).getByRole('img', { name: 'Линия плана, наблюдения и диапазон прогноза' })).toBeVisible()
})

test('100 бортов: счётчики и карта учитывают все борта потока', async ({ page, stub }) => {
  await stub.start({ STUB_VEHICLES: '100' })
  await page.goto('/')
  await expect(connectionPill(page, 'LIVE')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Состояние движения' })).toContainText(/100\s*в потоке/)
  await expect(page.getByText(/100 в снимке · 95 (на карте|с допустимой позицией) · 5 без допустимой позиции/)).toBeVisible()
})
