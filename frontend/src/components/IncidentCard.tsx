import { ArrowRight, BusFront, Clock3, Gauge, Info, MapPin, ShieldAlert } from 'lucide-react'
import type { Alert, Forecast, VehicleState } from '../types/contracts'
import { describeDelay, formatCountdown, formatDelay, formatPercent } from '../utils/format'
import { advanceContractTime, contractTimeMs, displayClock, secondsUntil } from '../utils/time'

interface Props {
  source: 'demo' | 'live'
  connected: boolean
  vehicle: VehicleState | undefined
  alert: Alert | undefined
  forecast: Forecast | null
  simTime: string
  positionAgeS: number | null
  forecastWallAgeS: number
}

const riskNames = { red: 'Критический риск', yellow: 'Требует внимания', green: 'В графике' }
const qualityNames = { full: 'Полное', degraded: 'Сниженное', fallback: 'Резервное' }

export default function IncidentCard({ source, connected, vehicle, alert, forecast, simTime, positionAgeS, forecastWallAgeS }: Props) {
  if (!vehicle && !alert) {
    return <aside className="panel incident-panel"><div className="panel-heading"><div><span className="eyebrow">Детали события</span><h2>Карточка борта</h2></div></div><div className="empty-panel"><BusFront size={30} /><strong>Выберите борт</strong><span>Нажмите на маркер или предупреждение.</span></div></aside>
  }

  const risk = forecast?.risk
  const estimatedArrival = forecast ? advanceContractTime(forecast.target_time_plan, forecast.delay_pred_s) : null
  const arrivalRemaining = estimatedArrival ? (contractTimeMs(estimatedArrival) - contractTimeMs(simTime)) / 1000 : null
  const forecastAgeS = forecast ? Math.max(0, (contractTimeMs(simTime) - contractTimeMs(forecast.issued_at)) / 1000 + forecastWallAgeS) : null
  const forecastStale = forecastAgeS != null && forecastAgeS > 120
  return (
    <aside className="panel incident-panel" aria-label="Карточка выбранного борта">
      <div className="panel-heading"><div><span className="eyebrow">Детали события</span><h2>Борт {vehicle?.tr_id ?? alert?.tr_id}</h2>{alert && <span className="incident-event-title">{alert.title} · {displayClock(alert.created_at)}</span>}</div><BusFront size={22} className="heading-icon" /></div>
      {forecast ? (
        <>
          <div className={`incident-risk-band risk-${risk}`}><ShieldAlert size={18} /><span>{risk ? riskNames[risk] : 'Риск не определен'}</span><strong title={describeDelay(forecast.delay_pred_s)}>{formatDelay(forecast.delay_pred_s)}</strong></div>
          <div className="incident-section target-section">
            <span className="eyebrow">Прогноз прибытия</span>
            <strong className="target-name"><MapPin size={17} />{forecast.target_stop_name}</strong>
            <div className="target-times">По плану {displayClock(forecast.target_time_plan)} · прогноз {displayClock(estimatedArrival ?? undefined)}</div>
            <div className="target-countdown"><Clock3 size={17} />{arrivalRemaining != null && arrivalRemaining >= 0 ? <>Через <strong>{formatCountdown(secondsUntil(estimatedArrival!, simTime))}</strong></> : <strong>Расчётное время прошло</strong>}<span>{source === 'demo' ? 'от времени симуляции' : 'от времени потока'}</span></div>
          </div>
          <div className="forecast-box">
            <div><span>Отклонение</span><strong>{describeDelay(forecast.delay_pred_s)}</strong></div>
            <div><span>Диапазон q10–q90</span><strong>{formatDelay(forecast.delay_q10_s)} – {formatDelay(forecast.delay_q90_s)}</strong></div>
            <div><span>Вероятность опоздания</span><strong>{formatPercent(forecast.p_late)}</strong></div>
            <div><span>Качество при расчёте</span><strong>{qualityNames[forecast.quality]}</strong></div>
            <div><span>Обновлён</span><strong>{displayClock(forecast.issued_at)}</strong></div>
            <div><span>Возраст прогноза</span><strong>{forecastAgeS != null && Number.isFinite(forecastAgeS) ? `${Math.floor(forecastAgeS / 60)} мин ${Math.round(forecastAgeS % 60)} с` : '—'}</strong></div>
          </div>
          {forecastStale && <div className="forecast-stale-warning" role="status">Прогноз выдан более 2 минут назад. Проверьте актуальность перед действием.</div>}
          <div className="incident-section cause-section">
            <span className="eyebrow">Причина прогноза</span>
            <strong>{forecast.cause.text}</strong>
            <p>{forecast.cause.evidence}</p>
            <span className="confidence-line"><Info size={14} /> Уверенность {formatPercent(forecast.cause.confidence)}</span>
          </div>
          {alert?.recommendation && (
            <div className="recommendation-box"><div className="recommendation-title"><Gauge size={17} />Рекомендация диспетчеру</div><p>{alert.recommendation.text}</p><span>{source === 'demo' ? 'Демонстрационный сценарий' : 'Данные потока'} <ArrowRight size={13} /></span><small>Рекомендация не отправлена водителю.</small></div>
          )}
          {!alert?.recommendation && <div className="incident-note">Рекомендация для этого борта пока недоступна.</div>}
          <details className="model-details"><summary>Сведения о расчёте</summary><span>Версия модели: {forecast.model_version}</span></details>
          {vehicle && <div className="position-line">Позиция: {Math.round(positionAgeS ?? vehicle.last_seen_s)} с назад · скорость на момент снимка {Math.round(vehicle.speed_kmh)} км/ч</div>}
          {vehicle?.stale && <div className="stale-warning"><ShieldAlert size={16} /> {connected ? `Последний пакет получен ${Math.round(positionAgeS ?? vehicle.last_seen_s)} с назад.` : 'Новый снимок пока не получен.'} Положение может быть неточным.</div>}
        </>
      ) : <div className="empty-panel"><Info size={28} /><strong>Прогноз пока недоступен</strong><span>{vehicle ? `Позиция: ${Math.round(positionAgeS ?? vehicle.last_seen_s)} с назад · скорость на момент снимка ${Math.round(vehicle.speed_kmh)} км/ч.` : 'Положение борта не получено.'}</span></div>}
    </aside>
  )
}
