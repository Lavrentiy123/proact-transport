import { ArrowRight, BusFront, Clock3, Gauge, Info, MapPin, ShieldAlert } from 'lucide-react'
import type { Alert, VehicleState } from '../types/contracts'
import { formatCountdown, formatDelay, formatPercent } from '../utils/format'
import { secondsUntil } from '../utils/time'

interface Props {
  source: 'demo' | 'live'
  connected: boolean
  vehicle: VehicleState | undefined
  alert: Alert | undefined
  simTime: string
}

const riskNames = { red: 'Критический риск', yellow: 'Требует внимания', green: 'В графике' }

export default function IncidentCard({ source, connected, vehicle, alert, simTime }: Props) {
  const forecast = vehicle?.forecast ?? alert?.forecast
  if (!vehicle && !alert) {
    return <aside className="panel incident-panel"><div className="panel-heading"><div><span className="eyebrow">Детали события</span><h2>Карточка борта</h2></div></div><div className="empty-panel"><BusFront size={30} /><strong>Выберите борт</strong><span>Нажмите на маркер или предупреждение.</span></div></aside>
  }

  const risk = forecast?.risk
  return (
    <aside className="panel incident-panel" aria-label="Карточка выбранного борта">
      <div className="panel-heading"><div><span className="eyebrow">Детали события</span><h2>Борт {vehicle?.tr_id ?? alert?.tr_id}</h2></div><BusFront size={22} className="heading-icon" /></div>
      {forecast ? (
        <>
          <div className={`incident-risk-band risk-${risk}`}><ShieldAlert size={18} /><span>{risk ? riskNames[risk] : 'Риск не определен'}</span><strong>{formatDelay(forecast.delay_pred_s)}</strong></div>
          <div className="incident-section target-section">
            <span className="eyebrow">Прогнозируемое прибытие</span>
            <strong className="target-name"><MapPin size={17} />{forecast.target_stop_name}</strong>
            <div className="target-countdown"><Clock3 size={17} />Через <strong>{formatCountdown(secondsUntil(forecast.target_time_plan, simTime))}</strong><span>{source === 'demo' ? 'от времени симуляции' : 'от времени потока'}</span></div>
          </div>
          <div className="forecast-box">
            <div><span>Отклонение</span><strong>{formatDelay(forecast.delay_pred_s)}</strong></div>
            <div><span>Диапазон q10–q90</span><strong>{formatDelay(forecast.delay_q10_s)} – {formatDelay(forecast.delay_q90_s)}</strong></div>
            <div><span>Вероятность опоздания</span><strong>{formatPercent(forecast.p_late)}</strong></div>
          </div>
          <div className="incident-section cause-section">
            <span className="eyebrow">Причина прогноза</span>
            <strong>{forecast.cause.text}</strong>
            <p>{forecast.cause.evidence}</p>
            <span className="confidence-line"><Info size={14} /> Уверенность {formatPercent(forecast.cause.confidence)}</span>
          </div>
          {alert?.recommendation && (
            <div className="recommendation-box"><div className="recommendation-title"><Gauge size={17} />Рекомендация диспетчеру</div><p>{alert.recommendation.text}</p><span>{source === 'demo' ? 'Демонстрационный сценарий' : 'Данные backend'} <ArrowRight size={13} /></span></div>
          )}
          {!alert?.recommendation && <div className="incident-note">Рекомендация для этого борта пока недоступна.</div>}
          {vehicle?.stale && <div className="stale-warning"><ShieldAlert size={16} /> {connected ? `Последний пакет получен ${Math.round(vehicle.last_seen_s)} с назад.` : 'Связь с потоком потеряна.'} Положение может быть неточным.</div>}
        </>
      ) : <div className="empty-panel"><Info size={28} /><strong>Прогноз пока недоступен</strong><span>Текущее положение борта видно на карте.</span></div>}
    </aside>
  )
}
