import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { alertFor, base } from '../test/fixtures'
import type { Alert } from '../types/contracts'
import AlertList from './AlertList'

function alerts(count: number): Alert[] {
  return Array.from({ length: count }, (_, index) => alertFor(100000 + index, `alert-${index}`, {
    priority: 1000 - index,
    risk: index % 2 === 0 ? 'red' : 'yellow',
  }))
}

function renderList(items: Alert[], props: Partial<Parameters<typeof AlertList>[0]> = {}) {
  const onSelect = vi.fn()
  render(<AlertList alerts={items} vehicles={base.vehicles!} selectedTrId={null} selectedAlertId={null} simTime={base.sim_time} loading={false} feed="live" onSelect={onSelect} {...props} />)
  return { onSelect, list: screen.getByRole('complementary', { name: 'Лента предупреждений' }) }
}

const eventButtons = (list: HTMLElement) => within(list).queryAllByRole('button', { name: /^Событие / })

describe('AlertList', () => {
  it('without alerts says so, and waits for the first snapshot while loading', () => {
    const { list } = renderList([])
    expect(within(list).getByText('Активных предупреждений нет')).toBeTruthy()
    expect(eventButtons(list)).toHaveLength(0)
  })

  it('shows the waiting state before the first snapshot', () => {
    renderList([], { loading: true })
    expect(screen.getByText('Ожидаем данные')).toBeTruthy()
  })

  it('one alert selects its vehicle', () => {
    const { list, onSelect } = renderList([base.alerts![0]])
    const [item] = eventButtons(list)
    expect(item.getAttribute('aria-label')).toContain(`борт ${base.alerts![0].tr_id}`)
    fireEvent.click(item)
    expect(onSelect).toHaveBeenCalledWith(base.alerts![0].tr_id, base.alerts![0].alert_id)
  })

  it('marks the selected alert as the current one', () => {
    const [first] = alerts(1)
    const { list } = renderList([first], { selectedTrId: first.tr_id, selectedAlertId: first.alert_id })
    expect(eventButtons(list)[0].getAttribute('aria-current')).toBe('true')
  })

  it('seven alerts fit without «Показать все»', () => {
    const { list } = renderList(alerts(7))
    expect(eventButtons(list)).toHaveLength(7)
    expect(within(list).queryByRole('button', { name: /Показать все/ })).toBeNull()
  })

  it('the eighth alert is behind «Показать все» and can be collapsed again', () => {
    const { list } = renderList(alerts(8))
    expect(eventButtons(list)).toHaveLength(7)
    fireEvent.click(within(list).getByRole('button', { name: 'Показать все · ещё 1 предупреждение' }))
    expect(eventButtons(list)).toHaveLength(8)
    fireEvent.click(within(list).getByRole('button', { name: 'Свернуть список' }))
    expect(eventButtons(list)).toHaveLength(7)
  })

  it('a hundred alerts keep the total and order by priority', () => {
    const { list } = renderList(alerts(100))
    expect(within(list).getByText('100')).toBeTruthy()
    expect(within(list).getByRole('button', { name: 'Показать все · ещё 93 предупреждения' })).toBeTruthy()
    expect(eventButtons(list)[0].getAttribute('aria-label')).toMatch(/^Событие alert-0:/)
  })

  it('filters by risk and vehicle number without changing the total', () => {
    const { list } = renderList(alerts(8))
    const filters = within(list).getByRole('group', { name: 'Фильтр предупреждений по риску' })
    fireEvent.click(within(filters).getByRole('button', { name: 'Внимание' }))
    expect(within(filters).getByRole('button', { name: 'Внимание' }).getAttribute('aria-pressed')).toBe('true')
    expect(eventButtons(list)).toHaveLength(4)
    expect(eventButtons(list).every((item) => item.getAttribute('aria-label')?.includes('внимание'))).toBe(true)
    expect(within(list).getByText('8')).toBeTruthy()
    fireEvent.click(within(filters).getByRole('button', { name: 'Все' }))
    fireEvent.change(within(list).getByRole('searchbox', { name: 'Поиск борта по номеру' }), { target: { value: '100005' } })
    expect(eventButtons(list)).toHaveLength(1)
    fireEvent.change(within(list).getByRole('searchbox', { name: 'Поиск борта по номеру' }), { target: { value: '424242' } })
    expect(within(list).getByText('Ничего не найдено')).toBeTruthy()
  })

  it('tells when the feed is paused or degraded', () => {
    renderList(alerts(1), { feed: 'paused' })
    expect(screen.getByText('Лента не обновляется: нет свежих данных')).toBeTruthy()
  })

  it('marks alerts of stale vehicles', () => {
    const stale = base.vehicles!.map((item) => ({ ...item, stale: true }))
    const { list } = renderList([base.alerts![0]], { vehicles: stale })
    expect(within(list).getByText('Данные устарели')).toBeTruthy()
  })
})
