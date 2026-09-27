import { Activity, BusFront, Clock3, Pause, Play, RotateCcw, Target, TriangleAlert, Wifi, WifiOff } from 'lucide-react'
import type { Scenario } from '../data/scenarios'
import type { ConnectionState } from '../data/liveTransport'
import type { HorizonMetrics, WsMessage } from '../types/contracts'
import { displayClock, displayDay } from '../utils/time'
import { RISK } from '../theme/risk'
import { Button, RiskMark, StatusDot, StatusPill, type StatusState } from '../ui'

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
  /** Горизонт и онлайн-MAE потока (только живой режим). */
  horizon?: HorizonMetrics | null
}

/** Онлайн-ошибка на первых десятках сверенных прогнозов шумная (старт дня, перемотка) — показываем с этого числа. */
const MIN_RESOLVED = 200

export default function StatusBar({
  snapshot, connected, source, liveConnection, liveStalled, hasVehicleSnapshot, hasAlertSnapshot, lastVehicleFrameAt, wallNow, liveTimeLagS, scenario, playing, onScenarioChange,
  onTogglePlayback, onRestart, onSourceChange, horizon,
}: Props) {
  const vehicles = snapshot.vehicles ?? []
  const alerts = (snapshot.alerts ?? []).filter((alert) => alert.status === 'active')
  const red = vehicles.filter((vehicle) => vehicle.forecast?.risk === 'red').length
  const yellow = vehicles.filter((vehicle) => vehicle.forecast?.risk === 'yellow').length
  const mode = source === 'demo' ? 'REPLAY' : snapshot.status?.mode ?? 'DEGRADED'
  const degraded = connected && mode === 'DEGRADED'
  const waiting = source === 'live' && liveConnection === 'connected' && !connected
  const count = (value: number) => hasVehicleSnapshot ? value : '—'
  // A broken socket outranks the stale-data detector: the dispatcher must see that the link is down.
  const offline = source === 'demo' ? !connected : liveConnection === 'disconnected'
  const connecting = source === 'live' && liveConnection === 'connecting'
  const pillState: StatusState = connected ? degraded ? 'degraded' : source === 'demo' ? 'demo' : 'live'
    : offline ? 'offline' : !connecting && liveStalled ? 'stale' : 'waiting'
  const pillText = connected ? degraded ? 'ДЕГРАДАЦИЯ' : mode : offline ? 'НЕТ СВЯЗИ' : connecting ? 'ПОДКЛЮЧЕНИЕ' : liveStalled ? 'ДАННЫЕ УСТАРЕЛИ' : waiting ? 'ОЖИДАНИЕ ДАННЫХ' : 'НЕТ СВЯЗИ'
  const dotState: StatusState = source === 'demo' ? connected ? 'demo' : 'offline'
    : connected ? degraded ? 'degraded' : 'live' : liveConnection === 'disconnected' ? 'offline' : liveStalled ? 'stale' : 'waiting'

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
          <StatusPill state={pillState} className="mode-pill" title={degraded ? 'Пакетов NDTP нет дольше 15 с: прогноз по расписанию' : undefined}
            icon={degraded ? <TriangleAlert size={14} /> : connected ? <Wifi size={14} /> : <WifiOff size={14} />}>{pillText}</StatusPill>
          <div className="header-time"><Clock3 size={17} /> {displayClock(snapshot.sim_time)} <span>МСК</span></div>
          <div className="header-day">{displayDay(snapshot.sim_time)}</div>
        </div>
      </header>

      <section className="summary-row" aria-label="Состояние движения">
        <div className="summary-intro">
          <span className="ui-eyebrow">Мониторинг маршрутов</span>
          <strong>Контроль движения</strong>
          <span className="summary-caption">Прогноз отклонений за 10–15 минут</span>
        </div>
        <div className="summary-metrics">
          <div className="summary-metric"><BusFront size={19} /><span><strong>{count(vehicles.length)}</strong><small>{source === 'demo' ? 'в демо-снимке' : connected ? 'в потоке' : 'в последнем снимке'}</small></span></div>
          <div className="summary-metric metric-red"><RiskMark variant="marker" risk="red" /><span><strong>{count(red)}</strong><small>{RISK.red.label.toLowerCase()}</small></span></div>
          <div className="summary-metric metric-yellow"><RiskMark variant="marker" risk="yellow" /><span><strong>{count(yellow)}</strong><small>{RISK.yellow.label.toLowerCase()}</small></span></div>
          <div className="summary-metric"><Activity size={19} /><span><strong>{hasAlertSnapshot ? alerts.length : '—'}</strong><small>алертов</small></span></div>
          {source === 'live' && horizon && <div className="summary-metric metric-horizon" title={`Сверено с фактическим прибытием: ${horizon.resolved_total} из ${horizon.forecasts_total}`}>
            <Target size={19} /><span><strong>{horizon.forecasts_total > 0 ? `${Math.round(horizon.share_lead_in_window * 100)}%` : '—'}</strong><small>{horizon.forecasts_total > 0 ? 'прогнозов за 10–15 мин' : 'прогнозов пока нет'}</small></span></div>}
          {source === 'live' && horizon && horizon.forecasts_total > 0 && (horizon.online_mae_model_s != null && horizon.resolved_total >= MIN_RESOLVED
            ? <div className="summary-metric metric-horizon" title={`Онлайн-MAE по журналу прогнозов потока: ${horizon.resolved_total} прогнозов сверены с фактическим прибытием`}>
              <span><strong>{Math.round(horizon.online_mae_model_s)} с</strong><small>ошибка прогноза{horizon.online_mae_baseline_s != null ? ` · бейзлайн ${Math.round(horizon.online_mae_baseline_s)} с` : ''}</small></span></div>
            : <div className="summary-metric metric-horizon" title="Ошибку показываем, когда с фактом сверено достаточно прогнозов: первые минуты после старта или перемотки шумные">
              <span><strong>—</strong><small>ошибка: сверено {horizon.resolved_total} из {MIN_RESOLVED}</small></span></div>)}
        </div>
      </section>

      <section className="demo-toolbar" aria-label="Управление источником данных">
        <div className="demo-toolbar-label"><StatusDot state={dotState} className="demo-dot" />{source === 'demo' ? 'Демо-сценарий' : degraded ? 'Поток в деградации' : connected ? 'Поток подключён' : offline ? 'Нет связи с потоком' : connecting ? 'Подключение к потоку' : liveStalled ? 'Данные устарели' : 'Ожидаем снимок'}</div>
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
              <Button variant="icon" onClick={onTogglePlayback} aria-label={playing ? 'Пауза' : 'Продолжить'} icon={playing ? <Pause size={16} /> : <Play size={16} />} />
              <Button variant="icon" onClick={onRestart} aria-label="Начать заново" icon={<RotateCcw size={16} />} />
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
          <span>ML-ядро: {snapshot.status == null ? 'нет данных' : snapshot.status.ml_core_ok ? 'доступно' : 'недоступно'}</span>
          <span>Контракт frontend: v0 · поток может быть локальным stub</span>
        </div></details>}
      </section>
    </>
  )
}
