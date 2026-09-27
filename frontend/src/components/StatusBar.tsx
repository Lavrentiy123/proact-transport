import { Activity, BusFront, Clock3, Pause, Play, RotateCcw, Target, TriangleAlert, Wifi, WifiOff } from 'lucide-react'
import type { Scenario } from '../data/scenarios'
import type { ConnectionState } from '../data/liveTransport'
import type { HorizonMetrics, WsMessage } from '../types/contracts'
import { ALERT_FORMS, plural } from '../utils/format'
import { displayClock, displayDay } from '../utils/time'
import { RISK } from '../theme/risk'
import { Button, RiskMark, StatusPill, type StatusState } from '../ui'

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
  /** Кадры, отброшенные проверкой контракта, и причина последнего отказа (BL-32). */
  droppedFrames: number
  lastDropReason: string | null
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

const debugMode = () => new URLSearchParams(window.location.search).get('debug') === '1'

export default function StatusBar({
  snapshot, connected, source, liveConnection, liveStalled, hasVehicleSnapshot, hasAlertSnapshot, lastVehicleFrameAt, wallNow, liveTimeLagS, droppedFrames, lastDropReason, scenario, playing, onScenarioChange,
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
  const sourceNote = source === 'demo' ? 'Демонстрационная версия: синтетический маршрут, прогноз из контрактного примера' : 'Живой поток: источник данных определяется подключённым сервером'
  const pillTitle = degraded ? `Пакетов NDTP нет дольше 15 с: прогноз по расписанию. ${sourceNote}` : sourceNote
  const alertCount = hasAlertSnapshot ? alerts.length : null

  return (
    <header className="topbar">
      <div className="brand-block">
        <div className="brand-mark" aria-hidden="true"><Activity size={18} strokeWidth={2.5} /></div>
        <div className="brand-name">ПроАкт<span>.Транспорт</span></div>
      </div>
      <StatusPill state={pillState} className="mode-pill" title={pillTitle}
        icon={degraded ? <TriangleAlert size={14} /> : connected ? <Wifi size={14} /> : <WifiOff size={14} />}>{pillText}</StatusPill>
      {source === 'demo' && <span className="source-note" title={sourceNote}>демо · синтетический маршрут</span>}
      <div className="header-time" title={displayDay(snapshot.sim_time)}><Clock3 size={15} /> {displayClock(snapshot.sim_time)} <span>МСК</span></div>

      <section className="header-counters" aria-label="Состояние движения">
        <span className="header-counter"><BusFront size={15} /><strong>{count(vehicles.length)}</strong><small>{source === 'demo' ? 'в демо-снимке' : connected ? 'в потоке' : 'в последнем снимке'}</small></span>
        <span className="header-counter metric-red"><RiskMark variant="marker" risk="red" /><strong>{count(red)}</strong><small>{RISK.red.label.toLowerCase()}</small></span>
        <span className="header-counter metric-yellow"><RiskMark variant="marker" risk="yellow" /><strong>{count(yellow)}</strong><small>{RISK.yellow.label.toLowerCase()}</small></span>
        <span className="header-counter"><strong>{alertCount ?? '—'}</strong><small>{alertCount == null ? 'предупреждений' : plural(alertCount, ALERT_FORMS)}</small></span>
        {source === 'live' && horizon && <span className="header-counter metric-horizon" title={`Доля прогнозов с горизонтом 10–15 мин. Сверено с фактическим прибытием: ${horizon.resolved_total} из ${horizon.forecasts_total}`}>
          <Target size={15} /><strong>{horizon.forecasts_total > 0 ? `${Math.round(horizon.share_lead_in_window * 100)}%` : '—'}</strong><small>{horizon.forecasts_total > 0 ? 'за 10–15 мин' : 'прогнозов пока нет'}</small></span>}
        {/* До 200 сверенных прогнозов (старт дня, перемотка replay) ошибку не показываем: «—» читается как сбой. */}
        {source === 'live' && horizon && horizon.online_mae_model_s != null && horizon.resolved_total >= MIN_RESOLVED &&
          <span className="header-counter metric-horizon" title={`Онлайн-MAE по журналу прогнозов потока: ${horizon.resolved_total} прогнозов сверены с фактическим прибытием${horizon.online_mae_baseline_s != null ? `; бейзлайн ${Math.round(horizon.online_mae_baseline_s)} с` : ''}`}>
            <strong>{Math.round(horizon.online_mae_model_s)} с</strong><small>ср. ошибка{horizon.online_mae_baseline_s != null && <span className="metric-extra"> · бейзлайн {Math.round(horizon.online_mae_baseline_s)} с</span>}</small></span>}
      </section>

      <section className="header-controls" aria-label="Управление источником данных">
        <label className="sr-only" htmlFor="source-select">Источник</label>
        <select id="source-select" value={source} onChange={(event) => onSourceChange(event.target.value as 'demo' | 'live')}>
          <option value="demo">Демо-сценарий</option>
          <option value="live">Живой поток</option>
        </select>
        {source === 'demo' && (
          <>
            <label className="sr-only" htmlFor="scenario-select">Сценарий</label>
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
        {source === 'live' && <details className="connection-details"><summary>Диагностика</summary><div>
          <span>WebSocket: {liveConnection === 'connected' ? 'соединён' : liveConnection === 'connecting' ? 'подключается' : 'отключён'}</span>
          <span>Снимок бортов: {lastVehicleFrameAt == null ? 'ещё не получен' : `${Math.max(0, Math.floor((wallNow - lastVehicleFrameAt) / 1000))} с назад`}</span>
          <span>Отставание позиций от часов потока: {hasVehicleSnapshot ? `${Math.floor(liveTimeLagS)} с` : 'нет данных'}</span>
          <span>Возраст пакета на момент статуса: {snapshot.status?.last_packet_age_s == null ? 'нет данных' : `${Math.round(snapshot.status.last_packet_age_s)} с`}</span>
          <span>Модель: {snapshot.status?.model_version || 'нет данных'}</span>
          <span>ML-ядро: {snapshot.status == null ? 'нет данных' : snapshot.status.ml_core_ok ? 'доступно' : 'недоступно'}</span>
          <span>Отброшено кадров: {droppedFrames}</span>
          <span>Последняя причина отказа: {lastDropReason ?? 'нет'}</span>
          {horizon && horizon.forecasts_total > 0 && <span>Сверено прогнозов с фактом: {horizon.resolved_total} из {horizon.forecasts_total}</span>}
          {debugMode() && <span>Контракт frontend: v0 · поток может быть локальным stub</span>}
        </div></details>}
      </section>
    </header>
  )
}
