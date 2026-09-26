import { Activity, BusFront, Clock3, Pause, Play, RotateCcw, Target, Wifi, WifiOff } from 'lucide-react'
import type { Scenario } from '../data/scenarios'
import type { HorizonMetrics, WsMessage } from '../types/contracts'
import { displayClock, displayDay } from '../utils/time'

interface Props {
  snapshot: WsMessage
  connected: boolean
  source: 'demo' | 'live'
  scenario: Scenario
  playing: boolean
  onScenarioChange: (scenario: Scenario) => void
  onTogglePlayback: () => void
  onRestart: () => void
  onSourceChange: (source: 'demo' | 'live') => void
  /** Горизонт и онлайн-MAE потока (только живой режим). */
  horizon?: HorizonMetrics | null
}

export default function StatusBar({
  snapshot, connected, source, scenario, playing, onScenarioChange,
  onTogglePlayback, onRestart, onSourceChange, horizon,
}: Props) {
  const vehicles = snapshot.vehicles ?? []
  const alerts = (snapshot.alerts ?? []).filter((alert) => alert.status === 'active')
  const red = vehicles.filter((vehicle) => vehicle.forecast?.risk === 'red').length
  const yellow = vehicles.filter((vehicle) => vehicle.forecast?.risk === 'yellow').length
  const mode = source === 'demo' ? 'REPLAY' : snapshot.status?.mode ?? 'DEGRADED'

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
          <div className={`mode-pill ${!connected ? 'is-disconnected' : mode === 'DEGRADED' ? 'is-degraded' : 'is-connected'}`}
            title={mode === 'DEGRADED' ? 'Пакетов NDTP нет дольше 15 с: прогноз по расписанию' : undefined}>
            {connected ? <Wifi size={15} /> : <WifiOff size={15} />}
            <span>{connected ? mode : 'НЕТ СВЯЗИ'}</span>
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
          <div className="summary-metric"><BusFront size={19} /><span><strong>{vehicles.length}</strong><small>бортов</small></span></div>
          <div className="summary-metric metric-red"><span className="metric-dot" /><span><strong>{red}</strong><small>критично</small></span></div>
          <div className="summary-metric metric-yellow"><span className="metric-dot" /><span><strong>{yellow}</strong><small>внимание</small></span></div>
          <div className="summary-metric"><Activity size={19} /><span><strong>{alerts.length}</strong><small>алертов</small></span></div>
          {source === 'live' && horizon && <div className="summary-metric metric-horizon" title={`Сверено с фактическим прибытием: ${horizon.resolved_total} из ${horizon.forecasts_total}`}>
            <Target size={19} /><span><strong>{horizon.forecasts_total > 0 ? `${Math.round(horizon.share_lead_in_window * 100)}%` : '—'}</strong><small>{horizon.forecasts_total > 0 ? 'прогнозов за 10–15 мин' : 'прогнозов пока нет'}</small></span></div>}
          {source === 'live' && horizon?.online_mae_model_s != null && <div className="summary-metric metric-horizon" title="Онлайн-MAE по журналу прогнозов потока, сверенному с прибытиями">
            <span><strong>{Math.round(horizon.online_mae_model_s)} с</strong><small>ошибка прогноза{horizon.online_mae_baseline_s != null ? ` · бейзлайн ${Math.round(horizon.online_mae_baseline_s)} с` : ''}</small></span></div>}
        </div>
      </section>

      <section className="demo-toolbar" aria-label="Управление источником данных">
        <div className="demo-toolbar-label"><span className="demo-dot" />{source === 'demo' ? 'ДЕМОНСТРАЦИЯ' : 'ПОДКЛЮЧЕНИЕ К ПОТОКУ'}</div>
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
      </section>
    </>
  )
}
