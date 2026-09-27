import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { base } from '../test/fixtures'
import type { Alert, VehicleState } from '../types/contracts'
import IncidentCard from './IncidentCard'

const alert = base.alerts![0]
const vehicle = base.vehicles!.find((item) => item.tr_id === alert.tr_id)!

function renderCard(props: Partial<Parameters<typeof IncidentCard>[0]> = {}) {
  return render(<IncidentCard source="live" connected vehicle={vehicle} alert={alert} forecast={alert.forecast} simTime={base.sim_time} positionAgeS={vehicle.last_seen_s} forecastWallAgeS={0} {...props} />)
}

describe('IncidentCard', () => {
  it('asks to pick a vehicle when nothing is selected', () => {
    renderCard({ vehicle: undefined, alert: undefined, forecast: null })
    expect(screen.getByText('Выберите борт')).toBeTruthy()
  })

  it('without a forecast explains why', () => {
    const plain: VehicleState = { ...vehicle, forecast: null }
    renderCard({ vehicle: plain, alert: undefined, forecast: null })
    expect(screen.getByText('Прогноз пока недоступен')).toBeTruthy()
  })

  it('a vehicle without a schedule says so', () => {
    renderCard({ vehicle: { ...vehicle, forecast: null }, alert: undefined, forecast: null, hasSchedule: false })
    expect(screen.getByText('Борт без расписания')).toBeTruthy()
  })

  it('shows the recommendation with both actions', () => {
    renderCard({ onAction: vi.fn() })
    const card = screen.getByRole('complementary', { name: 'Карточка выбранного борта' })
    expect(card).toBeTruthy()
    expect(screen.getByRole('heading', { name: `Борт ${vehicle.tr_id}` })).toBeTruthy()
    expect(screen.getByText('Рекомендация диспетчеру')).toBeTruthy()
    expect(screen.getByText(alert.recommendation!.text)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Отправить водителю' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Отклонить' })).toBeTruthy()
  })

  it('an alert without a recommendation offers to ask the driver', () => {
    const bare: Alert = { ...alert, recommendation: null }
    renderCard({ alert: bare, onAction: vi.fn() })
    expect(screen.getByText('Предупреждение без рекомендации')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Запросить обстановку' })).toBeTruthy()
  })

  it('sending locks both buttons until the action settles', async () => {
    let finish: () => void = () => {}
    const onAction = vi.fn(() => new Promise<void>((resolve) => { finish = resolve }))
    renderCard({ onAction })
    fireEvent.click(screen.getByRole('button', { name: 'Отправить водителю' }))
    expect(onAction).toHaveBeenCalledWith(alert, 'apply')
    const sending = screen.getByRole('button', { name: 'Отправка…' }) as HTMLButtonElement
    expect(sending.disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Отклонить' }) as HTMLButtonElement).disabled).toBe(true)
    await act(async () => { finish() })
    expect((screen.getByRole('button', { name: 'Отправить водителю' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('shows the driver reply after a successful action', () => {
    renderCard({ onAction: vi.fn(), outcome: { alert_id: alert.alert_id, status: 'applied', driver_message: 'Диспетчер: держать 24 км/ч', driver_reply: 'успеваю' } })
    const outcome = screen.getAllByRole('status').find((item) => item.textContent?.includes('Отправлено водителю'))
    expect(outcome?.textContent).toContain('Ответ водителя: «успеваю»')
  })

  it('shows why an action failed', () => {
    renderCard({ onAction: vi.fn(), outcome: { alert_id: alert.alert_id, error: 'алерт уже снят или решён' } })
    expect(screen.getByText(/Не удалось выполнить действие: алерт уже снят или решён/)).toBeTruthy()
  })

  it('without a link disables the actions, explains why and marks the data as frozen', () => {
    renderCard({ connected: false, onAction: vi.fn() })
    expect((screen.getByRole('button', { name: 'Отправить водителю' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Отклонить' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText('Нет связи — отправка недоступна')).toBeTruthy()
    expect(screen.getAllByText(/не обновляется с \d\d:\d\d:\d\d/)).toHaveLength(2)
    expect(screen.getByText('Вероятный диапазон')).toBeTruthy()
  })

  it('warns about a stale position', () => {
    renderCard({ vehicle: { ...vehicle, stale: true }, connected: false })
    expect(screen.getByText(/Новый снимок пока не получен\. Положение может быть неточным\./)).toBeTruthy()
  })
})
