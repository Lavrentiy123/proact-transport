import { useState } from 'react'
import { BusFront, Check, Clock3, Gauge, Info, MapPin, Route, Send, ShieldAlert, X } from 'lucide-react'
import type { ActionResponse, Alert, VehicleState } from '../types/contracts'
import { formatCountdown, formatDelay, formatPercent, stopLabel } from '../utils/format'
import { advanceContractTime, displayClock, secondsUntil } from '../utils/time'
import WhatIfPanel from './WhatIfPanel'

export type ActionOutcome = (ActionResponse & { error?: undefined }) | { alert_id: string; error: string }

interface Props {
  source: 'demo' | 'live'
  connected: boolean
  vehicle: VehicleState | undefined
  alert: Alert | undefined
  simTime: string
  /** Последняя пройденная остановка (по треку) — начало участка до целевой остановки. */
  segmentFrom?: string | null
  /** Результат последнего решения диспетчера по этому борту. */
  outcome?: ActionOutcome
  onAction?: (alert: Alert, action: 'apply' | 'dismiss') => Promise<void>
  /** false — у борта нет расписания (например, синтетический юнит эмулятора): прогноз не строится. */
  hasSchedule?: boolean
}

const riskNames = { red: 'Критический риск', yellow: 'Требует внимания', green: 'В графике' }
const qualityNotes = {
  full: null,
  degraded: 'Борт давно не выходил на связь — положение экстраполировано, прогноз менее надёжен.',
  fallback: 'Прогноз по расписанию: поток телеметрии или ML-ядро недоступны. Точность ниже обычной.',
}

function kmh(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${Math.round(value)} км/ч`
}

function dwell(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return value < 1 ? 'едет' : `${formatCountdown(value)} мин`
}

export default function IncidentCard({ source, connected, vehicle, alert, simTime, segmentFrom, outcome, onAction, hasSchedule }: Props) {
  const [busy, setBusy] = useState<'apply' | 'dismiss' | null>(null)
  const forecast = vehicle?.forecast ?? alert?.forecast
  if (!vehicle && !alert) {
    return <aside className="panel incident-panel"><div className="panel-heading"><div><span className="eyebrow">Детали события</span><h2>Карточка борта</h2></div></div><div className="empty-panel"><BusFront size={30} /><strong>Выберите борт</strong><span>Нажмите на маркер или предупреждение.</span></div></aside>
  }

  async function act(action: 'apply' | 'dismiss') {
    if (!alert || !onAction || busy) return
    setBusy(action)
    try { await onAction(alert, action) } finally { setBusy(null) }
  }

  const risk = forecast?.risk
  const qualityNote = forecast ? qualityNotes[forecast.quality] : null
  const expectedArrival = forecast ? advanceContractTime(forecast.target_time_plan, forecast.delay_pred_s) : null
  return (
    <aside className="panel incident-panel" aria-label="Карточка выбранного борта">
      <div className="panel-heading"><div><span className="eyebrow">Детали события</span><h2>Борт {vehicle?.tr_id ?? alert?.tr_id}</h2></div><BusFront size={22} className="heading-icon" /></div>
      {forecast ? (
        <>
          <div className={`incident-risk-band risk-${risk}`}><ShieldAlert size={18} /><span>{risk ? riskNames[risk] : 'Риск не определен'}</span><strong>{formatDelay(forecast.delay_pred_s)}</strong></div>
          {qualityNote && <div className="quality-note"><Info size={14} /> {qualityNote}</div>}
          <div className="incident-section target-section">
            <span className="eyebrow">Участок и целевая остановка</span>
            {segmentFrom && <span className="segment-line"><Route size={14} /> {segmentFrom} → {stopLabel(forecast.target_stop_name, forecast.target_stop_id)}</span>}
            <strong className="target-name"><MapPin size={17} />{stopLabel(forecast.target_stop_name, forecast.target_stop_id)}</strong>
            <div className="target-countdown"><Clock3 size={17} />План через <strong>{formatCountdown(secondsUntil(forecast.target_time_plan, simTime))}</strong><span>{source === 'demo' ? 'от времени симуляции' : 'от времени потока'}</span></div>
            <div className="target-countdown expected-arrival">Ожидаемое прибытие <strong>{displayClock(expectedArrival ?? undefined).slice(0, 5)}</strong><span>план {displayClock(forecast.target_time_plan).slice(0, 5)} + прогноз</span></div>
          </div>
          <div className="forecast-box">
            <div><span>Прогноз отклонения</span><strong>{formatDelay(forecast.delay_pred_s)}</strong></div>
            <div><span>Диапазон q10–q90</span><strong>{formatDelay(forecast.delay_q10_s)} – {formatDelay(forecast.delay_q90_s)}</strong></div>
            <div><span>Вероятность опоздания &gt; 2 мин</span><strong>{formatPercent(forecast.p_late)}</strong></div>
            <div><span>Горизонт прогноза</span><strong>{Number.isFinite(forecast.lead_s) ? `${formatCountdown(forecast.lead_s)} мин до плана` : '—'}</strong></div>
          </div>
          {alert?.recommendation?.target_speed_kmh != null && alert.recommendation.target_speed_kmh > 0 && (
            <WhatIfPanel key={alert.alert_id} forecast={alert.forecast} speedToPlanKmh={alert.recommendation.target_speed_kmh} />
          )}
          {vehicle && (
            <div className="forecast-box derived-box" aria-label="Текущее состояние борта">
              <div><span>Текущее отклонение (последняя остановка)</span><strong>{formatDelay(vehicle.cur_dev_s)}</strong></div>
              <div><span>Средняя скорость на перегоне</span><strong>{kmh(vehicle.seg_speed_kmh)}</strong></div>
              <div><span>Текущая стоянка</span><strong>{dwell(vehicle.dwell_s)}</strong></div>
            </div>
          )}
          <div className="incident-section cause-section">
            <span className="eyebrow">Причина прогноза</span>
            <strong>{forecast.cause.text}</strong>
            <p>{forecast.cause.evidence}</p>
            <span className="confidence-line"><Info size={14} /> Уверенность {formatPercent(forecast.cause.confidence)}</span>
          </div>
          {alert && (
            <div className="recommendation-box">
              <div className="recommendation-title"><Gauge size={17} />{alert.recommendation ? 'Рекомендация диспетчеру' : 'Алерт без рекомендации'}</div>
              <p>{alert.recommendation?.text ?? 'Прогноз опоздания без готовой меры: можно запросить у водителя обстановку на линии.'}</p>
              {onAction && (
                <div className="action-buttons">
                  <button className="action-button action-apply" disabled={busy != null} onClick={() => act('apply')}>
                    <Send size={14} /> {busy === 'apply' ? 'Отправка…' : alert.recommendation ? 'Отправить водителю' : 'Запросить обстановку'}
                  </button>
                  <button className="action-button action-dismiss" disabled={busy != null} onClick={() => act('dismiss')}>
                    <X size={14} /> {busy === 'dismiss' ? 'Отклоняю…' : 'Отклонить'}
                  </button>
                </div>
              )}
              <span>{source === 'demo' ? 'Демонстрационный сценарий: ответ водителя эмулируется' : 'Канал NDTP «диспетчер ↔ водитель»; ответ водителя в демо эмулируется'}</span>
            </div>
          )}
          {outcome && 'status' in outcome && (
            <div className="action-outcome">
              <span><Check size={14} /> {outcome.status === 'applied' ? 'Отправлено водителю' : outcome.status === 'dismissed' ? 'Алерт отклонён' : `Статус: ${outcome.status}`}</span>
              <span className="outcome-message">{outcome.driver_message}</span>
              {outcome.driver_reply && <strong>Ответ водителя: «{outcome.driver_reply}»</strong>}
            </div>
          )}
          {outcome && 'error' in outcome && outcome.error && (
            <div className="action-outcome is-error"><X size={14} /> Не удалось выполнить действие: {outcome.error}</div>
          )}
          {!alert && !outcome && <div className="incident-note">Алерта по борту нет: он поднимается при красном риске (прогноз опоздания от 5 мин или вероятность опоздания больше 2 мин от 80 %).</div>}
          {vehicle?.stale && <div className="stale-warning"><ShieldAlert size={16} /> {connected ? `Последний пакет получен ${Math.round(vehicle.last_seen_s)} с назад.` : 'Связь с потоком потеряна.'} Положение может быть неточным.</div>}
        </>
      ) : hasSchedule === false
        ? <div className="empty-panel"><Info size={28} /><strong>Борт без расписания</strong><span>Для него прогноз не строится (например, синтетический юнит эмулятора) — только положение на карте.</span></div>
        : <div className="empty-panel"><Info size={28} /><strong>Прогноз пока недоступен</strong><span>В окне 10–15 минут у борта нет плановой остановки. Текущее положение видно на карте.</span></div>}
    </aside>
  )
}
