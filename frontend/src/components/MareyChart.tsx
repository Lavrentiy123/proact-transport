import { BarChart3 } from 'lucide-react'
import type { TrackResponse, VehicleState } from '../types/contracts'
import { haversineMeters } from '../utils/geo'
import { contractTimeMs, displayClock } from '../utils/time'

interface Props { source: 'demo' | 'live'; track: TrackResponse | null; vehicle: VehicleState | undefined; simTime: string }

const W = 1000
const H = 178
const left = 70
const right = 965
const top = 18
const bottom = 140

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

export default function MareyChart({ source, track, vehicle, simTime }: Props) {
  if (!track || track.stops.length < 2) {
    return <section className="marey-panel"><div className="marey-heading"><BarChart3 size={17} /><strong>Диаграмма движения</strong><span>Выберите борт с маршрутом</span></div></section>
  }

  const stops = [...track.stops].sort((a, b) => a.seq - b.seq)
  const distances = stops.map((_, index) => index === 0 ? 0 :
    stops.slice(1, index + 1).reduce((sum, current, offset) =>
      sum + haversineMeters(stops[offset].lon, stops[offset].lat, current.lon, current.lat), 0))
  const totalDistance = Math.max(distances.at(-1) ?? 1, 1)
  const startTime = contractTimeMs(stops[0].time_plan)
  const endTime = Math.max(contractTimeMs(stops.at(-1)!.time_plan) + 9 * 60_000, contractTimeMs(simTime) + 60_000)
  const x = (time: number) => left + ((time - startTime) / (endTime - startTime)) * (right - left)
  const y = (distance: number) => bottom - (distance / totalDistance) * (bottom - top)
  const planPoints = stops.map((stop, index) => `${x(contractTimeMs(stop.time_plan))},${y(distances[index])}`).join(' ')
  const observedPoints = track.trail
    .map(([time, lat, lon]) => `${x(contractTimeMs(time))},${y(closestDistance(lat, lon, stops, distances))}`)
    .join(' ')
  const forecast = vehicle?.forecast
  const targetIndex = stops.findIndex((stop) => stop.stop_id === forecast?.target_stop_id)
  const targetDistance = targetIndex >= 0 ? distances[targetIndex] : totalDistance
  const planTargetTime = forecast ? contractTimeMs(forecast.target_time_plan) : Number.NaN
  const forecastX = forecast ? x(planTargetTime + forecast.delay_pred_s * 1000) : Number.NaN
  const q10X = forecast ? x(planTargetTime + forecast.delay_q10_s * 1000) : Number.NaN
  const q90X = forecast ? x(planTargetTime + forecast.delay_q90_s * 1000) : Number.NaN

  return (
    <section className="marey-panel" aria-label={`Диаграмма движения борта ${track.tr_id}`}>
      <div className="marey-heading"><div><BarChart3 size={18} /><strong>Движение борта {track.tr_id}</strong><span>Время → · расстояние по маршруту ↑</span></div><div className="marey-legend"><span className="plan-line">План</span><span className="fact-line">Наблюдение</span><span className="forecast-line">Прогноз q10–q90</span></div></div>
      <div className="marey-chart-scroll"><svg className="marey-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Линия плана, наблюдения и диапазон прогноза">
        {[0, .25, .5, .75, 1].map((ratio) => <g key={ratio}><line x1={left} x2={right} y1={y(totalDistance * ratio)} y2={y(totalDistance * ratio)} stroke="#2d4552" strokeDasharray="4 5" /><text x={left - 12} y={y(totalDistance * ratio) + 4} textAnchor="end" fill="#8ca6b2" fontSize="10">{(totalDistance * ratio / 1000).toFixed(1)} км</text></g>)}
        {stops.map((stop) => <g key={stop.stop_id}><line x1={x(contractTimeMs(stop.time_plan))} x2={x(contractTimeMs(stop.time_plan))} y1={top} y2={bottom} stroke="#2d4552" strokeDasharray="3 7" /><text x={x(contractTimeMs(stop.time_plan))} y="160" textAnchor="middle" fill="#8ca6b2" fontSize="10">{displayClock(stop.time_plan).slice(0, 5)}</text></g>)}
        <polyline points={planPoints} fill="none" stroke="#79c4d8" strokeWidth="2.5" strokeDasharray="7 5" />
        <polyline points={observedPoints} fill="none" stroke="#efbe70" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        {forecast && Number.isFinite(forecastX) && <g><line x1={q10X} x2={q90X} y1={y(targetDistance)} y2={y(targetDistance)} stroke="#fa8c85" strokeWidth="10" strokeOpacity=".3" strokeLinecap="round" /><line x1={q10X} x2={q90X} y1={y(targetDistance)} y2={y(targetDistance)} stroke="#ff9990" strokeWidth="2" /><circle cx={forecastX} cy={y(targetDistance)} r="6" fill="#ff897f" stroke="#fff" strokeWidth="2" /><text x={Math.min(forecastX + 12, right - 120)} y={y(targetDistance) - 12} fill="#ffc3ae" fontSize="11">+{Math.round(forecast.delay_pred_s / 60)} мин</text></g>}
        <line x1={Math.max(left, Math.min(right, x(contractTimeMs(simTime))))} x2={Math.max(left, Math.min(right, x(contractTimeMs(simTime))))} y1={top} y2={bottom} stroke="#f3d693" strokeOpacity=".5" />
      </svg></div>
      <div className="marey-footnote">{source === 'demo' ? 'Схема построена по демонстрационному маршруту.' : 'Схема построена по маршруту из backend.'} Положение наблюдения проецируется на маршрут.</div>
    </section>
  )
}
