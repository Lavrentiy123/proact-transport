import { Activity, BusFront, Clock3, Pause, Play, RotateCcw, Wifi, WifiOff } from 'lucide-react'
import type { Scenario } from '../data/scenarios'
import type { ConnectionState } from '../data/liveTransport'
import type { WsMessage } from '../types/contracts'
import { displayClock, displayDay } from '../utils/time'

interface Props {
  snapshot: WsMessage
  connected: boolean
  source: 'demo' | 'live'
  liveConnection: ConnectionState
  liveStalled: boolean
  hasVehicleSnapshot: boolean
  hasAlertSnapshot: boolean
  lastVehicleFrameAt: number | null
  wallNow: number
  liveTimeLagS: number
  scenario: Scenario
  playing: boolean
  onScenarioChange: (scenario: Scenario) => void
  onTogglePlayback: () => void
  onRestart: () => void
  onSourceChange: (source: 'demo' | 'live') => void
}

export default function StatusBar({
  snapshot, connected, source, liveConnection, liveStalled, hasVehicleSnapshot, hasAlertSnapshot, lastVehicleFrameAt, wallNow, liveTimeLagS, scenario, playing, onScenarioChange,
  onTogglePlayback, onRestart, onSourceChange,
}: Props) {
  const vehicles = snapshot.vehicles ?? []
  const alerts = (snapshot.alerts ?? []).filter((alert) => alert.status === 'active')
  const red = vehicles.filter((vehicle) => vehicle.forecast?.risk === 'red').length
  const yellow = vehicles.filter((vehicle) => vehicle.forecast?.risk === 'yellow').length
  const mode = source === 'demo' ? 'REPLAY' : snapshot.status?.mode ?? 'DEGRADED'
  const waiting = source === 'live' && liveConnection === 'connected' && !connected
  const count = (value: number) => hasVehicleSnapshot ? value : '—'

  return (
    <>
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark"><Activity size={25} strokeWidth={2.5} /></div>
          <div>
            <div className="brand-name">ПроАкт<span>.Транспорт</span></div>
            <div className="brand-subtitle">Оперативный центр движения</div>
          </div>
        </div>
        <div className="topbar-right">
          <div className={`mode-pill ${connected ? 'is-connected' : waiting ? 'is-waiting' : 'is-disconnected'}`}>
            {connected ? <Wifi size={15} /> : <WifiOff size={15} />}
            <span>{connected ? mode : liveStalled ? 'ДАННЫЕ УСТАРЕЛИ' : waiting ? 'ОЖИДАНИЕ ДАННЫХ' : 'НЕТ СВЯЗИ'}</span>
          </div>
          <div className="header-time"><Clock3 size={17} /> {displayClock(snapshot.sim_time)} <span>МСК</span></div>
          <div className="header-day">{displayDay(snapshot.sim_time)}</div>
        </div>
      </header>

      <section className="summary-row" aria-label="Состояние движения">
        <div className="summary-intro">
          <span className="eyebrow">Мониторинг маршрутов</span>
          <strong>Контроль движения</strong>
          <span className="summary-caption">Прогноз отклонений за 10–15 минут</span>
        </div>
        <div className="summary-metrics">
          <div className="summary-metric"><BusFront size={19} /><span><strong>{count(vehicles.length)}</strong><small>{source === 'demo' ? 'в демо-снимке' : connected ? 'в потоке' : 'в последнем снимке'}</small></span></div>
          <div className="summary-metric metric-red"><span className="metric-dot" /><span><strong>{count(red)}</strong><small>критично</small></span></div>
          <div className="summary-metric metric-yellow"><span className="metric-dot" /><span><strong>{count(yellow)}</strong><small>внимание</small></span></div>
          <div className="summary-metric"><Activity size={19} /><span><strong>{hasAlertSnapshot ? alerts.length : '—'}</strong><small>алертов</small></span></div>
        </div>
      </section>

      <section className="demo-toolbar" aria-label="Управление источником данных">
        <div className="demo-toolbar-label"><span className="demo-dot" />{source === 'demo' ? 'Демо-сценарий' : connected ? 'Поток подключён' : liveStalled ? 'Данные устарели' : waiting ? 'Ожидаем снимок' : 'Подключение к потоку'}</div>
        <div className="toolbar-controls">
          <label className="toolbar-select-label" htmlFor="source-select">Источник</label>
          <select id="source-select" value={source} onChange={(event) => onSourceChange(event.target.value as 'demo' | 'live')}>
            <option value="demo">Демо-сценарий</option>
            <option value="live">Живой поток</option>
          </select>
          {source === 'demo' && (
            <>
              <label className="toolbar-select-label" htmlFor="scenario-select">Сценарий</label>
              <select id="scenario-select" value={scenario} onChange={(event) => onScenarioChange(event.target.value as Scenario)}>
                <option value="normal">Обычный поток</option>
                <option value="many">Пик алертов</option>
                <option value="empty">Нет данных</option>
                <option value="disconnected">Потеря связи</option>
              </select>
              <button className="toolbar-button" onClick={onTogglePlayback} aria-label={playing ? 'Пауза' : 'Продолжить'}>
                {playing ? <Pause size={16} /> : <Play size={16} />}
              </button>
              <button className="toolbar-button" onClick={onRestart} aria-label="Начать заново"><RotateCcw size={16} /></button>
              <span className="playback-speed">×{snapshot.status?.replay_speed ?? 1}</span>
            </>
          )}
        </div>
        {source === 'live' && <details className="connection-details"><summary>Диагностика</summary><div>
          <span>WebSocket: {liveConnection === 'connected' ? 'соединён' : liveConnection === 'connecting' ? 'подключается' : 'отключён'}</span>
          <span>Снимок бортов: {lastVehicleFrameAt == null ? 'ещё не получен' : `${Math.max(0, Math.floor((wallNow - lastVehicleFrameAt) / 1000))} с назад`}</span>
          <span>Отставание позиций от часов потока: {hasVehicleSnapshot ? `${Math.floor(liveTimeLagS)} с` : 'нет данных'}</span>
          <span>Возраст пакета на момент статуса: {snapshot.status?.last_packet_age_s == null ? 'нет данных' : `${Math.round(snapshot.status.last_packet_age_s)} с`}</span>
          <span>Модель: {snapshot.status?.model_version || 'нет данных'}</span>
          <span>Контракт frontend: v0 · поток может быть локальным stub</span>
        </div></details>}
      </section>
    </>
  )
}
