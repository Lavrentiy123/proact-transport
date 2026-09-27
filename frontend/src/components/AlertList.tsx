import { useEffect, useRef, useState } from 'react'
import { BellRing, Search } from 'lucide-react'
import type { Alert, VehicleState } from '../types/contracts'
import { ALERT_FORMS, formatDelay, planCountdown, plural, stopLabel } from '../utils/format'
import { contractTimeMs } from '../utils/time'
import { RISK, riskMeta } from '../theme/risk'
import { Button, EmptyState, Panel, PanelHeader, RiskMark, StatusDot, StatusPill } from '../ui'

interface Props {
  alerts: Alert[]
  vehicles: VehicleState[]
  selectedTrId: number | null
  selectedAlertId: string | null
  simTime: string
  loading: boolean
  /** live — data follows the stream, degraded — telemetry is lost and forecasts use the schedule, paused — no fresh frames. */
  feed: 'live' | 'degraded' | 'paused'
  onSelect: (trId: number, alertId: string) => void
  /** Выбор борта без предупреждения (список «Под наблюдением», когда активных предупреждений нет). */
  onSelectVehicle?: (trId: number) => void
}

const WATCH_LIMIT = 5

const savedRiskKey = 'proact-transport:alert-risk-filter:v1'

function initialRiskFilter(): 'all' | 'red' | 'yellow' {
  try {
    const saved = window.localStorage.getItem(savedRiskKey)
    return saved === 'red' || saved === 'yellow' ? saved : 'all'
  } catch { return 'all' }
}

export default function AlertList({ alerts, vehicles, selectedTrId, selectedAlertId, simTime, loading, feed, onSelect, onSelectVehicle }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [riskFilter, setRiskFilter] = useState<'all' | 'red' | 'yellow'>(initialRiskFilter)
  const [query, setQuery] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const selectedItemRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    try { window.localStorage.setItem(savedRiskKey, riskFilter) } catch { /* Private storage can be unavailable. */ }
  }, [riskFilter])
  const active = alerts.filter((alert) => alert.status === 'active').sort((a, b) =>
    b.priority - a.priority || b.created_at.localeCompare(a.created_at) || a.alert_id.localeCompare(b.alert_id))
  const filtered = active.filter((alert) =>
    (riskFilter === 'all' || alert.risk === riskFilter) &&
    (query.trim() === '' || String(alert.tr_id).includes(query.trim())))
  const visible = expanded || query.trim() || riskFilter !== 'all' ? filtered : filtered.slice(0, 7)
  const activeOrder = active.map((alert) => alert.alert_id).join('|')
  const visibleOrder = visible.map((alert) => alert.alert_id).join('|')
  // Предупреждение поднимается только на красном риске и держится минуты; в паузах лента показывает борта с
  // жёлтым и красным риском, чтобы диспетчер сразу видел, за кем следить.
  const watch = !loading && active.length === 0 && onSelectVehicle
    ? vehicles.filter((vehicle) => vehicle.forecast && (vehicle.forecast.risk === 'red' || vehicle.forecast.risk === 'yellow'))
      .sort((a, b) => (b.forecast?.delay_pred_s ?? 0) - (a.forecast?.delay_pred_s ?? 0)).slice(0, WATCH_LIMIT)
    : []

  useEffect(() => {
    if (selectedAlertId && active.findIndex((item) => item.alert_id === selectedAlertId) >= 7) setExpanded(true)
  }, [selectedAlertId, activeOrder])

  useEffect(() => {
    const container = scrollRef.current
    const item = selectedItemRef.current
    if (!container || !item) return
    const containerBox = container.getBoundingClientRect()
    const itemBox = item.getBoundingClientRect()
    if (itemBox.top < containerBox.top) container.scrollTop -= containerBox.top - itemBox.top
    if (itemBox.bottom > containerBox.bottom) container.scrollTop += itemBox.bottom - containerBox.bottom
  }, [selectedAlertId, visibleOrder])

  return (
    <Panel as="aside" id="alerts-feed" tabIndex={-1} className="alerts-panel" aria-label="Лента предупреждений">
      <PanelHeader title="Предупреждения" actions={<span className="count-badge">{active.length}</span>}>
        <span className="alerts-subheading">По приоритету · прогноз на 10–15 минут</span>
      </PanelHeader>
      <div className="alerts-tools">
        <label className="alerts-search"><Search size={15} aria-hidden="true" /><span className="sr-only">Поиск борта по номеру</span><input type="search" inputMode="numeric" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Номер борта" /></label>
        <div className="alerts-filters" role="group" aria-label="Фильтр предупреждений по риску">
          <Button variant="ghost" aria-pressed={riskFilter === 'all'} onClick={() => setRiskFilter('all')}>Все</Button>
          <Button variant="ghost" aria-pressed={riskFilter === 'red'} onClick={() => setRiskFilter('red')}>{RISK.red.label}</Button>
          <Button variant="ghost" aria-pressed={riskFilter === 'yellow'} onClick={() => setRiskFilter('yellow')}>{RISK.yellow.label}</Button>
        </div>
      </div>
      {visible.length === 0 && watch.length > 0 ? (
        <>
          <EmptyState className="alerts-empty-compact" title="Активных предупреждений нет"
            hint="Под наблюдением — борта с жёлтым и красным риском. Нажмите, чтобы открыть прогноз." />
          <div className="alerts-scroll watch-list" role="group" aria-label="Под наблюдением">
            {watch.map((vehicle) => {
              const forecast = vehicle.forecast!
              const target = stopLabel(forecast.target_stop_name, forecast.target_stop_id)
              const countdown = planCountdown((contractTimeMs(forecast.target_time_plan) - contractTimeMs(simTime)) / 1000)
              const selected = vehicle.tr_id === selectedTrId
              return (
                <button key={vehicle.tr_id} className={`alert-item watch-item risk-${forecast.risk}${selected ? ' selected' : ''}`}
                  onClick={() => onSelectVehicle?.(vehicle.tr_id)} aria-current={selected || undefined}
                  aria-label={`Под наблюдением: борт ${vehicle.tr_id}, ${riskMeta(forecast.risk).label.toLowerCase()}, прогноз ${formatDelay(forecast.delay_pred_s)}, к ${target}, ${countdown}`}>
                  <div className="alert-item-top">
                    <RiskMark risk={forecast.risk} />
                    <span className="alert-vehicle">Борт {vehicle.tr_id}</span>
                    <span className="alert-delay">{formatDelay(forecast.delay_pred_s)}</span>
                  </div>
                  <div className="alert-item-bottom">к {target} · {countdown}</div>
                </button>
              )
            })}
          </div>
        </>
      ) : visible.length === 0 ? (
        <EmptyState icon={<BellRing size={28} />} title={loading ? 'Ожидаем данные' : filtered.length === 0 && active.length > 0 ? 'Ничего не найдено' : 'Активных предупреждений нет'}
          hint={loading ? 'Лента появится после получения снимка.' : active.length > 0 ? 'Измените фильтр или номер борта.' : 'Новые предупреждения появятся здесь.'} />
      ) : (
        <div className="alerts-scroll" ref={scrollRef}>
          {visible.map((alert) => {
            const vehicle = vehicles.find((item) => item.tr_id === alert.tr_id)
            const selected = alert.alert_id === selectedAlertId && alert.tr_id === selectedTrId
            const riskLabel = riskMeta(alert.risk).label.toLowerCase()
            const target = stopLabel(alert.forecast.target_stop_name, alert.forecast.target_stop_id)
            const countdown = planCountdown((contractTimeMs(alert.forecast.target_time_plan) - contractTimeMs(simTime)) / 1000)
            const cause = alert.forecast.cause?.text?.trim() || ''
            return (
              <button
                key={alert.alert_id}
                ref={selected ? selectedItemRef : undefined}
                className={`alert-item risk-${alert.risk}${selected ? ' selected' : ''}`}
                onClick={() => onSelect(alert.tr_id, alert.alert_id)}
                aria-current={selected || undefined}
                aria-label={`Борт ${alert.tr_id}, ${riskLabel}, отклонение ${formatDelay(alert.forecast.delay_pred_s)}${cause ? `, причина: ${cause}` : ''}, к ${target}, ${countdown}`}
                title={cause ? `Причина: ${cause}` : undefined}
              >
                <div className="alert-item-top">
                  <RiskMark risk={alert.risk} />
                  <span className="alert-vehicle">Борт {alert.tr_id}</span>
                  <span className="alert-delay">{formatDelay(alert.forecast.delay_pred_s)}</span>
                </div>
                <div className="alert-item-bottom">к {target} · {countdown}</div>
                {cause && <div className="alert-item-cause">{cause}</div>}
                {vehicle?.stale && <StatusPill state="stale" className="stale-tag">Данные устарели</StatusPill>}
              </button>
            )
          })}
          {riskFilter === 'all' && query.trim() === '' && filtered.length > 7 && <Button block className="alerts-more" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? 'Свернуть список' : `Показать все · ещё ${filtered.length - 7} ${plural(filtered.length - 7, ALERT_FORMS)}`}</Button>}
        </div>
      )}
      <div className="panel-footer"><StatusDot state={feed === 'live' ? 'live' : feed === 'degraded' ? 'degraded' : 'waiting'} className="live-dot" />{feed === 'live' ? 'Лента обновляется вслед за потоком' : feed === 'degraded' ? 'Телеметрии нет: прогнозы по расписанию' : 'Лента не обновляется: нет свежих данных'}<a className="mobile-map-jump" href="#vehicle-map">К карте</a></div>
    </Panel>
  )
}
