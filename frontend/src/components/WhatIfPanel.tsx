import { useState } from 'react'
import { FlaskConical } from 'lucide-react'
import type { Forecast } from '../types/contracts'
import { formatDelay } from '../utils/format'
import { advanceContractTime, displayClock } from '../utils/time'
import { KeyValue, Panel } from '../ui'

interface Props {
  forecast: Forecast
  /** Средняя скорость, с которой борт успевает к плановому времени (из рекомендации backend). */
  speedToPlanKmh: number
}

const MIN_KMH = 5
const MAX_KMH = 60

function clamp(value: number): number {
  return Math.min(MAX_KMH, Math.max(MIN_KMH, value))
}

/**
 * What-If «скорость до остановки». Дистанция по маршруту восстанавливается из рекомендации:
 * backend считает `v = D / lead`, значит `D = v · lead`. Прогноз модели задаёт ожидаемую среднюю скорость
 * `D / (lead + прогноз)`; ползунок показывает, каким будет отклонение при другой средней скорости.
 * Кинематическая оценка без стоянок на промежуточных остановках — поэтому при скорости модели она совпадает
 * с её прогнозом, а в стороны от неё — приближение.
 */
export default function WhatIfPanel({ forecast, speedToPlanKmh }: Props) {
  const lead = forecast.lead_s
  const distM = (speedToPlanKmh * lead) / 3.6
  const modelSpeed = (distM / Math.max(lead + forecast.delay_pred_s, 60)) * 3.6
  // шаг 0.1 км/ч: в начальном положении оценка совпадает с прогнозом модели (без скачка от округления)
  const [speed, setSpeed] = useState(() => Math.round(clamp(modelSpeed) * 10) / 10)
  if (!(distM > 0) || !Number.isFinite(modelSpeed)) return null

  const delay = (distM / (speed / 3.6)) - lead
  const arrival = advanceContractTime(forecast.target_time_plan, delay)
  const gain = forecast.delay_pred_s - delay
  return (
    <Panel as="div" variant="inset" className="whatif-box" aria-label="Что если: скорость до остановки">
      <div className="whatif-title"><FlaskConical size={15} /> Что если · средняя скорость до остановки</div>
      <label className="whatif-slider">
        <input type="range" min={MIN_KMH} max={MAX_KMH} step={0.1} value={speed}
          onChange={(event) => setSpeed(Number(event.target.value))} aria-label="Средняя скорость до остановки, км/ч" />
        <strong>{Math.round(speed)} км/ч</strong>
      </label>
      <KeyValue variant="dense" className="whatif-rows" rows={[
        { label: 'Отклонение при этой скорости', value: formatDelay(delay) },
        { label: 'Прибытие', value: displayClock(arrival ?? undefined).slice(0, 5) },
        Math.abs(gain) < 5
          ? { label: 'Как в прогнозе модели', value: '—' }
          : { label: gain > 0 ? 'Отыгрывает к прогнозу модели' : 'Теряет к прогнозу модели', value: formatDelay(Math.abs(gain)).replace(/^\+/, '') },
      ]} />
      <span className="whatif-note">
        Модель ожидает ~{Math.round(modelSpeed)} км/ч; по плану успевает при {Math.round(speedToPlanKmh)} км/ч.
        До остановки ~{(distM / 1000).toFixed(1)} км по маршруту; стоянки на промежуточных остановках не учтены.
      </span>
    </Panel>
  )
}
