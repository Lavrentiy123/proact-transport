import { BarChart3 } from 'lucide-react'
import type { Forecast, TrackResponse } from '../types/contracts'
import { haversineMeters } from '../utils/geo'
import { describeDelay, stopLabel } from '../utils/format'
import { advanceContractTime, contractTimeMs, displayClock } from '../utils/time'
import { planTimesOrdered } from '../utils/track'
import { riskKey } from '../theme/risk'
import { Panel, PanelHeader } from '../ui'

interface Props { source: 'demo' | 'live'; track: TrackResponse | null; forecast: Forecast | null; simTime: string; loading: boolean; routeError: boolean }

const W = 1000
const H = 178
const left = 70
const right = 965
const top = 18
const bottom = 140
const WINDOW_BACK_MS = 30 * 60_000
const WINDOW_AHEAD_MS = 40 * 60_000

/** В живом режиме backend отдаёт расписание борта на весь день — показываем только окно вокруг «сейчас»
 * (плюс целевую остановку), иначе на диаграмме сотни подписей и её невозможно прочитать. */
function windowStops(stops: TrackResponse['stops'], simTime: string, targetStopId: number | undefined): TrackResponse['stops'] {
  const now = contractTimeMs(simTime)
  if (!Number.isFinite(now)) return stops
  const inside = stops.filter((stop) => {
    const t = contractTimeMs(stop.time_plan)
    return (t >= now - WINDOW_BACK_MS && t <= now + WINDOW_AHEAD_MS) || stop.stop_id === targetStopId
  })
  if (inside.length >= 2) return inside
  const nearest = [...stops].sort((a, b) =>
    Math.abs(contractTimeMs(a.time_plan) - now) - Math.abs(contractTimeMs(b.time_plan) - now)).slice(0, 10)
  return nearest.sort((a, b) => a.seq - b.seq)
}

function closestDistance(lat: number, lon: number, stops: TrackResponse['stops'], distances: number[]): number {
  let best = Number.POSITIVE_INFINITY
  let along = 0
  for (let index = 0; index < stops.length - 1; index++) {
    const a = stops[index]
    const b = stops[index + 1]
    const scale = Math.cos(lat * Math.PI / 180)
    const dx = (b.lon - a.lon) * scale
    const dy = b.lat - a.lat
    const t = Math.max(0, Math.min(1, (((lon - a.lon) * scale) * dx + (lat - a.lat) * dy) / (dx * dx + dy * dy || 1)))
    const distance = Math.hypot((lon - a.lon - t * (b.lon - a.lon)) * scale, lat - a.lat - t * (b.lat - a.lat))
    if (distance < best) { best = distance; along = distances[index] + t * (distances[index + 1] - distances[index]) }
  }
  return along
}

function MareyPlaceholder({ text }: { text: string }) {
  return <Panel className="marey-panel"><PanelHeader compact className="marey-heading" titleAs="strong" icon={<BarChart3 size={17} />} title="Диаграмма движения"><span>{text}</span></PanelHeader></Panel>
}

export default function MareyChart({ source, track, forecast, simTime, loading, routeError }: Props) {
  if (!track || track.stops.length < 2) {
    return <MareyPlaceholder text={loading ? 'Загрузка маршрута…' : routeError ? 'Маршрут недоступен; положение и прогноз сохранены' : 'Выберите борт с маршрутом'} />
  }

  const sorted = [...track.stops].sort((a, b) => a.seq - b.seq)
  const stops = source === 'live' ? windowStops(sorted, simTime, forecast?.target_stop_id) : sorted
  if (stops.length < 2) {
    return <MareyPlaceholder text="Нет плановых остановок рядом с текущим временем" />
  }
  const planTimes = stops.map((stop) => contractTimeMs(stop.time_plan))
  if (!planTimesOrdered(planTimes)) {
    return <MareyPlaceholder text="Некорректный порядок плановых остановок" />
  }
  const distances = stops.map((_, index) => index === 0 ? 0 :
    stops.slice(1, index + 1).reduce((sum, current, offset) =>
      sum + haversineMeters(stops[offset].lon, stops[offset].lat, current.lon, current.lat), 0))
  const totalDistance = distances.at(-1) ?? 0
  if (!Number.isFinite(totalDistance) || totalDistance < 1) {
    return <MareyPlaceholder text="Недостаточно расстояния между остановками" />
  }
  const targetIndex = stops.findIndex((stop) => stop.stop_id === forecast?.target_stop_id)
  const planTargetTime = forecast ? contractTimeMs(forecast.target_time_plan) : Number.NaN
  const forecastTimes = forecast && targetIndex >= 0 ? [
    planTargetTime + forecast.delay_pred_s * 1000,
    planTargetTime + forecast.delay_q10_s * 1000,
    planTargetTime + forecast.delay_q90_s * 1000,
  ] : []
  // Points before the first stop of the live window would all project onto its start.
  const windowStart = source === 'live' ? planTimes[0] - 60_000 : Number.NEGATIVE_INFINITY
  const trail = track.trail.filter(([time]) => contractTimeMs(time) <= contractTimeMs(simTime) && contractTimeMs(time) >= windowStart)
  const orderedTrail = trail.every(([time], index) => index === 0 || contractTimeMs(time) >= contractTimeMs(trail[index - 1][0]))
  const observedTrail = orderedTrail ? trail : []
  const visibleTimes = [...planTimes, ...observedTrail.map(([time]) => contractTimeMs(time)), ...forecastTimes, contractTimeMs(simTime)]
    .filter(Number.isFinite)
  const startTime = Math.min(...visibleTimes) - 60_000
  const endTime = Math.max(...visibleTimes, planTimes.at(-1)! + 9 * 60_000) + 60_000
  const x = (time: number) => left + ((time - startTime) / (endTime - startTime)) * (right - left)
  const y = (distance: number) => bottom - (distance / totalDistance) * (bottom - top)
  const planPoints = stops.map((stop, index) => `${x(contractTimeMs(stop.time_plan))},${y(distances[index])}`).join(' ')
  const observedPoints = observedTrail
    .map(([time, lat, lon]) => `${x(contractTimeMs(time))},${y(closestDistance(lat, lon, stops, distances))}`)
    .join(' ')
  const targetDistance = targetIndex >= 0 ? distances[targetIndex] : Number.NaN
  const forecastX = forecast ? x(planTargetTime + forecast.delay_pred_s * 1000) : Number.NaN
  const q10X = forecast ? x(planTargetTime + forecast.delay_q10_s * 1000) : Number.NaN
  const q90X = forecast ? x(planTargetTime + forecast.delay_q90_s * 1000) : Number.NaN
  const labelEvery = Math.max(1, Math.ceil(stops.length / 6))
  const forecastArrival = forecast ? advanceContractTime(forecast.target_time_plan, forecast.delay_pred_s) : null
  const forecastRisk = `risk-${riskKey(forecast?.risk)}`

  return (
    <Panel className="marey-panel" aria-label={`Диаграмма движения борта ${track.tr_id}`}>
      <PanelHeader compact className="marey-heading" titleAs="strong" icon={<BarChart3 size={18} />} title={`Движение борта ${track.tr_id}`}
        actions={<div className="marey-legend"><span className="plan-line">План</span><span className="fact-line">Наблюдение</span><span className={`forecast-line ${forecastRisk}`}>Прогноз q10–q90</span></div>}>
        <span>Время → · расстояние по маршруту ↑</span>
      </PanelHeader>
      <div className="marey-chart-scroll"><svg className="marey-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Линия плана, наблюдения и диапазон прогноза">
        {[0, .25, .5, .75, 1].map((ratio) => <g key={ratio}><line className="marey-grid" x1={left} x2={right} y1={y(totalDistance * ratio)} y2={y(totalDistance * ratio)} strokeDasharray="4 5" /><text className="marey-axis" x={left - 12} y={y(totalDistance * ratio) + 4} textAnchor="end" fontSize="12">{(totalDistance * ratio / 1000).toFixed(1)} км</text></g>)}
        {stops.map((stop, index) => <g key={`${stop.stop_id}-${stop.seq}`}><title>{stopLabel(stop.name, stop.stop_id)} · план {displayClock(stop.time_plan)}</title><line className="marey-grid" x1={x(contractTimeMs(stop.time_plan))} x2={x(contractTimeMs(stop.time_plan))} y1={top} y2={bottom} strokeDasharray="3 7" />{(index % labelEvery === 0 || index === stops.length - 1) && <text className="marey-axis" x={x(contractTimeMs(stop.time_plan))} y="160" textAnchor="middle" fontSize="12">{displayClock(stop.time_plan).slice(0, 5)}</text>}</g>)}
        <polyline className="marey-plan" points={planPoints} fill="none" strokeWidth="2.5" strokeDasharray="7 5" />
        <polyline className="marey-observed" points={observedPoints} fill="none" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        {forecast && targetIndex >= 0 && Number.isFinite(forecastX) && <g className={`marey-forecast ${forecastRisk}`}><line className="marey-forecast-range" x1={q10X} x2={q90X} y1={y(targetDistance)} y2={y(targetDistance)} strokeWidth="10" strokeOpacity=".3" strokeLinecap="round" /><line className="marey-forecast-range" x1={q10X} x2={q90X} y1={y(targetDistance)} y2={y(targetDistance)} strokeWidth="2" /><circle cx={forecastX} cy={y(targetDistance)} r="6" strokeWidth="2" /><text x={Math.min(forecastX + 12, right - 150)} y={y(targetDistance) - 12} fontSize="12">{describeDelay(forecast.delay_pred_s)}</text></g>}
        <line x1={Math.max(left, Math.min(right, x(contractTimeMs(simTime))))} x2={Math.max(left, Math.min(right, x(contractTimeMs(simTime))))} y1={top} y2={bottom} className="marey-now" strokeOpacity=".5" />
      </svg></div>
      <div className="marey-footnote">{source === 'demo' ? 'Демонстрационный маршрут.' : 'Окно −30…+40 мин вокруг времени потока; маршрут и трек обновляются каждые 15 с.'} {stopLabel(stops[0].name, stops[0].stop_id)} → {stopLabel(stops.at(-1)!.name, stops.at(-1)!.stop_id)}. {orderedTrail ? 'Наблюдения до текущего времени проецируются на маршрут.' : 'Наблюдения скрыты: неверный порядок времени.'} {forecast && targetIndex < 0 ? 'Целевая остановка прогноза отсутствует в маршруте.' : ''}</div>
      <p className="sr-only">План от {displayClock(stops[0].time_plan)} до {displayClock(stops.at(-1)!.time_plan)}. Последнее наблюдение {observedTrail.length > 0 ? displayClock(observedTrail.at(-1)![0]) : 'отсутствует'}. {forecastArrival && targetIndex >= 0 ? `${describeDelay(forecast!.delay_pred_s)} к остановке ${stopLabel(forecast!.target_stop_name, forecast!.target_stop_id)}, прогноз прибытия ${displayClock(forecastArrival)}.` : 'Прогноз на остановке маршрута отсутствует.'}</p>
    </Panel>
  )
}
