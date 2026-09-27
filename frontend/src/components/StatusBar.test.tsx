import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ConnectionState } from '../data/liveTransport'
import { base, copy } from '../test/fixtures'
import type { WsMessage } from '../types/contracts'
import StatusBar from './StatusBar'

type Props = Parameters<typeof StatusBar>[0]

function renderBar(props: Partial<Props> = {}) {
  const handlers = { onScenarioChange: vi.fn(), onTogglePlayback: vi.fn(), onRestart: vi.fn(), onSourceChange: vi.fn() }
  render(<StatusBar
    snapshot={base} connected source="demo" liveConnection="disconnected" liveStalled={false}
    hasVehicleSnapshot hasAlertSnapshot lastVehicleFrameAt={null} wallNow={0} liveTimeLagS={0}
    droppedFrames={0} lastDropReason={null} scenario="normal" playing {...handlers} {...props}
  />)
  return handlers
}

function live(mode: 'LIVE' | 'DEGRADED'): WsMessage {
  const snapshot = copy(base)
  snapshot.status!.mode = mode
  return snapshot
}

const liveProps = (connection: ConnectionState, extra: Partial<Props> = {}): Partial<Props> => ({ source: 'live', liveConnection: connection, ...extra })

describe('StatusBar: connection pill', () => {
  it.each<[string, Partial<Props>]>([
    ['REPLAY', {}],
    ['НЕТ СВЯЗИ', { connected: false, scenario: 'disconnected' }],
    ['LIVE', liveProps('connected', { snapshot: live('LIVE') })],
    ['ДЕГРАДАЦИЯ', liveProps('connected', { snapshot: live('DEGRADED') })],
    ['ПОДКЛЮЧЕНИЕ', liveProps('connecting', { connected: false })],
    ['НЕТ СВЯЗИ', liveProps('disconnected', { connected: false })],
    ['ДАННЫЕ УСТАРЕЛИ', liveProps('connected', { connected: false, liveStalled: true })],
    ['ОЖИДАНИЕ ДАННЫХ', liveProps('connected', { connected: false })],
  ])('shows %s', (text, props) => {
    renderBar(props)
    expect(screen.getByText(text)).toBeTruthy()
  })
})

describe('StatusBar', () => {
  it('counts vehicles, risks and active alerts', () => {
    renderBar()
    const summary = screen.getByRole('region', { name: 'Состояние движения' })
    expect(summary.textContent).toMatch(new RegExp(`${base.vehicles!.length}\\s*в демо-снимке`))
    expect(summary.textContent).toMatch(/1\s*критично/)
    expect(summary.textContent).toMatch(/1\s*алертов/)
  })

  it('shows dashes until the first snapshot', () => {
    renderBar(liveProps('connected', { connected: false, hasVehicleSnapshot: false, hasAlertSnapshot: false }))
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(4)
  })

  it('demo controls pause and restart', () => {
    const handlers = renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Пауза' }))
    fireEvent.click(screen.getByRole('button', { name: 'Начать заново' }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Сценарий' }), { target: { value: 'many' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Источник' }), { target: { value: 'live' } })
    expect(handlers.onTogglePlayback).toHaveBeenCalledOnce()
    expect(handlers.onRestart).toHaveBeenCalledOnce()
    expect(handlers.onScenarioChange).toHaveBeenCalledWith('many')
    expect(handlers.onSourceChange).toHaveBeenCalledWith('live')
  })

  it('paused demo offers to continue', () => {
    renderBar({ playing: false })
    expect(screen.getByRole('button', { name: 'Продолжить' })).toBeTruthy()
  })

  it('live diagnostics show dropped frames and the last reason (BL-32)', () => {
    renderBar(liveProps('connected', { snapshot: live('LIVE'), droppedFrames: 3, lastDropReason: 'повреждённый JSON' }))
    fireEvent.click(screen.getByText('Диагностика'))
    expect(screen.getByText('Отброшено кадров: 3')).toBeTruthy()
    expect(screen.getByText('Последняя причина отказа: повреждённый JSON')).toBeTruthy()
    expect(screen.getByText('WebSocket: соединён')).toBeTruthy()
  })

  it('live diagnostics without drops', () => {
    renderBar(liveProps('connected', { snapshot: live('LIVE') }))
    expect(screen.getByText('Отброшено кадров: 0')).toBeTruthy()
    expect(screen.getByText('Последняя причина отказа: нет')).toBeTruthy()
  })
})
