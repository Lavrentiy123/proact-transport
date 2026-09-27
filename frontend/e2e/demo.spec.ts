import type { Page } from '@playwright/test'
import { connectionPill, expect, headerClock, test } from './stub'

/** «Начать заново» и сразу «Пауза»; повтор, если между нажатиями успел пройти шаг воспроизведения. */
async function restartPaused(page: Page) {
  await expect(async () => {
    await page.getByRole('button', { name: 'Начать заново' }).click()
    await page.getByRole('button', { name: 'Пауза' }).click()
    expect(await headerClock(page)).toBe('12:40:00')
  }).toPass({ timeout: 10_000 })
}

test('S6: демо по сценарию показа (docs/DEMO_SCRIPT.md)', async ({ page }) => {
  await page.goto('/?source=demo')
  await expect(page.getByRole('combobox', { name: 'Источник' })).toHaveValue('demo')
  const scenario = page.getByRole('combobox', { name: 'Сценарий' })
  await expect(scenario).toHaveValue('normal')
  await expect(connectionPill(page, 'REPLAY')).toBeVisible()

  await restartPaused(page)
  const summary = page.getByRole('region', { name: 'Состояние движения' })
  await expect(summary).toContainText(/3\s*в демо-снимке/)
  await expect(summary).toContainText(/1\s*критично/)
  await expect(summary).toContainText(/1\s*алертов/)
  const card = page.getByRole('complementary', { name: 'Карточка выбранного борта' })
  await expect(card.getByRole('heading', { name: 'Борт 131672' })).toBeVisible()
  await expect(card.getByText('Рекомендация диспетчеру')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Карта движения бортов' })).toBeVisible()

  // Пауза останавливает часы.
  await page.waitForTimeout(2_000)
  expect(await headerClock(page)).toBe('12:40:00')

  // Второе предупреждение приходит через 45 модельных секунд (≈ 9 с при ×5).
  await page.getByRole('button', { name: 'Продолжить' }).click()
  const feed = page.getByRole('complementary', { name: 'Лента предупреждений' })
  const second = feed.getByRole('button', { name: /^Событие demo-122658-event/ })
  await expect(second).toBeVisible({ timeout: 12_000 })
  await expect(summary).toContainText(/2\s*алертов/)
  await page.getByRole('button', { name: 'Пауза' }).click()
  await second.click()
  await expect(card.getByRole('heading', { name: 'Борт 122658' })).toBeVisible()
  await expect(second).toHaveAttribute('aria-pressed', 'true')

  await scenario.selectOption('empty')
  // The empty card has no accessible name yet, so the text is looked up on the page.
  await expect(page.getByText('Выберите борт', { exact: true })).toBeVisible()
  await expect(feed.getByText('Активных предупреждений нет')).toBeVisible()

  await scenario.selectOption('disconnected')
  await expect(connectionPill(page, 'НЕТ СВЯЗИ')).toBeVisible()
  await expect(page.getByText('Демо-поток прерван. На экране последний снимок; положение бортов может быть устаревшим.')).toBeVisible()

  await scenario.selectOption('normal')
  await expect(connectionPill(page, 'REPLAY')).toBeVisible()
  await restartPaused(page)
  await expect(summary).toContainText(/1\s*алертов/)
})

test('демо → живой поток без backend → демо', async ({ page }) => {
  await page.goto('/?source=demo')
  await page.getByRole('combobox', { name: 'Источник' }).selectOption('live')
  await expect(connectionPill(page, 'НЕТ СВЯЗИ').or(connectionPill(page, 'ПОДКЛЮЧЕНИЕ'))).toBeVisible()
  await expect(page.getByRole('complementary', { name: 'Лента предупреждений' }).getByText('Ожидаем данные')).toBeVisible()
  await page.getByRole('combobox', { name: 'Источник' }).selectOption('demo')
  await expect(connectionPill(page, 'REPLAY')).toBeVisible()
  await expect(page.getByRole('complementary', { name: 'Карточка выбранного борта' }).getByRole('heading', { name: 'Борт 131672' })).toBeVisible()
})
