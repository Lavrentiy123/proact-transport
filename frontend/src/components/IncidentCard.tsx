import { useState } from 'react'
import { BusFront, Check, Clock3, Gauge, Info, MapPin, Route, Send, ShieldAlert, X } from 'lucide-react'
import type { ActionResponse, Alert, Forecast, VehicleState } from '../types/contracts'
import { describeDelay, formatCountdown, formatDelay, formatPercent, stopLabel } from '../utils/format'
import { advanceContractTime, contractTimeMs, displayClock, secondsUntil } from '../utils/time'
import WhatIfPanel from './WhatIfPanel'
import { Banner, Button, EmptyState, KeyValue, Panel, PanelHeader, RiskBadge } from '../ui'

export type ActionOutcome = (ActionResponse & { error?: undefined }) | { alert_id: string; error: string }

interface Props {
  source: 'demo' | 'live'
  connected: boolean
  vehicle: VehicleState | undefined
  alert: Alert | undefined
  forecast: Forecast | null
  simTime: string
  positionAgeS: number | null
  forecastWallAgeS: number
  /** Последняя пройденная остановка (по треку) — начало участка до целевой остановки. */
  segmentFrom?: string | null
  /** Результат последнего решения диспетчера по этому борту. */
  outcome?: ActionOutcome
  onAction?: (alert: Alert, action: 'apply' | 'dismiss') => Promise<void>
  /** false — у борта нет расписания (например, синтетический юнит эмулятора): прогноз не строится. */
  hasSchedule?: boolean
}

const qualityNames = { full: 'Полное', degraded: 'Сниженное', fallback: 'Резервное' }
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

export default function IncidentCard({ source, connected, vehicle, alert, forecast, simTime, positionAgeS, forecastWallAgeS, segmentFrom, outcome, onAction, hasSchedule }: Props) {
  const [busy, setBusy] = useState<'apply' | 'dismiss' | null>(null)
  if (!vehicle && !alert) {
    return <Panel as="aside" className="incident-panel"><PanelHeader eyebrow="Детали события" title="Карточка борта" /><EmptyState icon={<BusFront size={30} />} title="Выберите борт" hint="Нажмите на маркер или предупреждение." /></Panel>
  }

  async function act(action: 'apply' | 'dismiss') {
    if (!alert || !onAction || busy) return
    setBusy(action)
    try { await onAction(alert, action) } finally { setBusy(null) }
  }

  const risk = forecast?.risk
  const qualityNote = forecast ? qualityNotes[forecast.quality] : null
  const targetName = forecast ? stopLabel(forecast.target_stop_name, forecast.target_stop_id) : ''
  const estimatedArrival = forecast ? advanceContractTime(forecast.target_time_plan, forecast.delay_pred_s) : null
  const planRemaining = forecast ? (contractTimeMs(forecast.target_time_plan) - contractTimeMs(simTime)) / 1000 : null
  const forecastAgeS = forecast ? Math.max(0, (contractTimeMs(simTime) - contractTimeMs(forecast.issued_at)) / 1000 + forecastWallAgeS) : null
  const forecastStale = forecastAgeS != null && forecastAgeS > 120
  const positionLine = vehicle ? `Позиция: ${Math.round(positionAgeS ?? vehicle.last_seen_s)} с назад · скорость на момент снимка ${Math.round(vehicle.speed_kmh)} км/ч` : null
  return (
    <Panel as="aside" className="incident-panel" aria-label="Карточка выбранного борта">
      <PanelHeader eyebrow="Детали события" title={`Борт ${vehicle?.tr_id ?? alert?.tr_id}`} actions={<BusFront size={22} className="heading-icon" />}>
        {alert && <span className="incident-event-title">{alert.title} · {displayClock(alert.created_at)}</span>}
      </PanelHeader>
      {forecast ? (
        <>
          <RiskBadge variant="strip" risk={risk} className="incident-risk-band" value={formatDelay(forecast.delay_pred_s)} valueTitle={describeDelay(forecast.delay_pred_s)} />
          {qualityNote && <Banner tone="warning" inset live={false} className="quality-note" icon={<Info size={14} />}>{qualityNote}</Banner>}
          <div className="incident-section target-section">
            <span className="ui-eyebrow">Участок и целевая остановка</span>
            {segmentFrom && <span className="segment-line"><Route size={14} /> {segmentFrom} → {targetName}</span>}
            <strong className="target-name"><MapPin size={17} />{targetName}</strong>
            <div className="target-countdown"><Clock3 size={17} />{planRemaining != null && planRemaining >= 0 ? <>План через <strong>{formatCountdown(secondsUntil(forecast.target_time_plan, simTime))}</strong></> : <strong>Плановое время прошло</strong>}<span>{source === 'demo' ? 'от времени симуляции' : 'от времени потока'}</span></div>
            <div className="target-countdown expected-arrival">Ожидаемое прибытие <strong>{displayClock(estimatedArrival ?? undefined).slice(0, 5)}</strong><span>план {displayClock(forecast.target_time_plan).slice(0, 5)} + прогноз</span></div>
          </div>
          <KeyValue className="forecast-box" stale={forecastStale} rows={[
            { label: 'Прогноз отклонения', value: describeDelay(forecast.delay_pred_s) },
            { label: 'Диапазон q10–q90', value: `${formatDelay(forecast.delay_q10_s)} – ${formatDelay(forecast.delay_q90_s)}` },
            { label: 'Вероятность опоздания > 2 мин', value: formatPercent(forecast.p_late) },
            { label: 'Горизонт прогноза', value: Number.isFinite(forecast.lead_s) ? `${Math.round(forecast.lead_s / 60)} мин до плана` : '—' },
            { label: 'Качество при расчёте', value: qualityNames[forecast.quality] },
            { label: 'Обновлён', value: displayClock(forecast.issued_at) },
            { label: 'Возраст прогноза', value: forecastAgeS != null && Number.isFinite(forecastAgeS) ? `${Math.floor(forecastAgeS / 60)} мин ${Math.round(forecastAgeS % 60)} с` : '—' },
          ]} />
          {forecastStale && <Banner tone="warning" inset className="forecast-stale-warning">Прогноз выдан более 2 минут назад. Проверьте актуальность перед действием.</Banner>}
          {alert?.recommendation?.target_speed_kmh != null && alert.recommendation.target_speed_kmh > 0 && (
            <WhatIfPanel key={alert.alert_id} forecast={alert.forecast} speedToPlanKmh={alert.recommendation.target_speed_kmh} />
          )}
          {vehicle && (
            <KeyValue className="forecast-box derived-box" aria-label="Текущее состояние борта" rows={[
              { label: 'Текущее отклонение (последняя остановка)', value: formatDelay(vehicle.cur_dev_s) },
              { label: 'Средняя скорость на перегоне', value: kmh(vehicle.seg_speed_kmh) },
              { label: 'Текущая стоянка', value: dwell(vehicle.dwell_s) },
            ]} />
          )}
          <div className="incident-section cause-section">
            <span className="ui-eyebrow">Причина прогноза</span>
            <strong>{forecast.cause.text}</strong>
            <p>{forecast.cause.evidence}</p>
            <span className="confidence-line"><Info size={14} /> Уверенность {formatPercent(forecast.cause.confidence)}</span>
          </div>
          {alert && (
            <Panel as="div" variant="inset" className="recommendation-box">
              <div className="recommendation-title"><Gauge size={17} />{alert.recommendation ? 'Рекомендация диспетчеру' : 'Предупреждение без рекомендации'}</div>
              <p>{alert.recommendation?.text ?? 'Прогноз опоздания без готовой меры: можно запросить у водителя обстановку на линии.'}</p>
              {onAction && (
                <div className="action-buttons">
                  <Button variant="primary" icon={<Send size={14} />} loading={busy === 'apply'} disabled={busy != null} onClick={() => act('apply')}>
                    {busy === 'apply' ? 'Отправка…' : alert.recommendation ? 'Отправить водителю' : 'Запросить обстановку'}
                  </Button>
                  <Button icon={<X size={14} />} loading={busy === 'dismiss'} disabled={busy != null} onClick={() => act('dismiss')}>
                    {busy === 'dismiss' ? 'Отклоняю…' : 'Отклонить'}
                  </Button>
                </div>
              )}
              <small>{source === 'demo' ? 'Демонстрационный сценарий: ответ водителя эмулируется' : 'Канал NDTP «диспетчер ↔ водитель»; ответ водителя в демо эмулируется'}</small>
            </Panel>
          )}
          {outcome && 'status' in outcome && (
            <Banner tone="success" inset className="action-outcome" icon={<Check size={14} />}>
              <span>{outcome.status === 'applied' ? 'Отправлено водителю' : outcome.status === 'dismissed' ? 'Предупреждение отклонено' : `Статус: ${outcome.status}`}</span>
              <span className="outcome-message">{outcome.driver_message}</span>
              {outcome.driver_reply && <strong>Ответ водителя: «{outcome.driver_reply}»</strong>}
            </Banner>
          )}
          {outcome && 'error' in outcome && outcome.error && (
            <Banner tone="error" inset className="action-outcome is-error" icon={<X size={14} />}>Не удалось выполнить действие: {outcome.error}</Banner>
          )}
          {!alert && !outcome && <div className="incident-note">Предупреждения по борту нет: оно поднимается при красном риске (прогноз опоздания от 5 мин или вероятность опоздания больше 2 мин от 80 %).</div>}
          <details className="model-details"><summary>Сведения о расчёте</summary><span>Версия модели: {forecast.model_version}</span></details>
          {positionLine && <div className="position-line">{positionLine}</div>}
          {vehicle?.stale && <Banner tone="warning" inset live={false} className="stale-warning" icon={<ShieldAlert size={16} />}>{connected ? `Последний пакет получен ${Math.round(positionAgeS ?? vehicle.last_seen_s)} с назад.` : 'Новый снимок пока не получен.'} Положение может быть неточным.</Banner>}
        </>
      ) : hasSchedule === false
        ? <EmptyState icon={<Info size={28} />} title="Борт без расписания" hint={`Для него прогноз не строится (например, синтетический юнит эмулятора) — только положение на карте.${positionLine ? ` ${positionLine}.` : ''}`} />
        : <EmptyState icon={<Info size={28} />} title="Прогноз пока недоступен" hint={vehicle ? `В окне 10–15 минут у борта нет плановой остановки. ${positionLine}.` : 'Положение борта не получено.'} />}
    </Panel>
  )
}
