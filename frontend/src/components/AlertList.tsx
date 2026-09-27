import { useEffect, useRef, useState } from 'react'
import { BellRing, ChevronRight, Search } from 'lucide-react'
import type { Alert, VehicleState } from '../types/contracts'
import { formatCountdown, formatDelay, stopLabel } from '../utils/format'
import { secondsUntil } from '../utils/time'
import { displayClock } from '../utils/time'
import { RISK, riskMeta } from '../theme/risk'

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
}

const alertWord = (count: number) => ({
  zero: 'предупреждений', one: 'предупреждение', two: 'предупреждения',
  few: 'предупреждения', many: 'предупреждений', other: 'предупреждения',
})[new Intl.PluralRules('ru-RU').select(count)]
const savedRiskKey = 'proact-transport:alert-risk-filter:v1'

function initialRiskFilter(): 'all' | 'red' | 'yellow' {
  try {
    const saved = window.localStorage.getItem(savedRiskKey)
    return saved === 'red' || saved === 'yellow' ? saved : 'all'
  } catch { return 'all' }
}

export default function AlertList({ alerts, vehicles, selectedTrId, selectedAlertId, simTime, loading, feed, onSelect }: Props) {
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
    <aside className="panel alerts-panel" aria-label="Лента предупреждений">
      <div className="panel-heading">
        <div><span className="eyebrow">Очередь диспетчера</span><h2>Предупреждения</h2></div>
        <span className="count-badge">{active.length}</span>
      </div>
      <div className="alerts-subheading">По приоритету · прогноз на 10–15 минут</div>
      <div className="alerts-tools">
        <label className="alerts-search"><Search size={15} aria-hidden="true" /><span className="sr-only">Поиск борта по номеру</span><input type="search" inputMode="numeric" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Номер борта" /></label>
        <div className="alerts-filters" role="group" aria-label="Фильтр предупреждений по риску">
          <button type="button" aria-pressed={riskFilter === 'all'} onClick={() => setRiskFilter('all')}>Все</button>
          <button type="button" aria-pressed={riskFilter === 'red'} onClick={() => setRiskFilter('red')}>{RISK.red.label}</button>
          <button type="button" aria-pressed={riskFilter === 'yellow'} onClick={() => setRiskFilter('yellow')}>{RISK.yellow.label}</button>
        </div>
      </div>
      {visible.length === 0 ? (
        <div className="empty-panel"><BellRing size={28} /><strong>{loading ? 'Ожидаем данные' : filtered.length === 0 && active.length > 0 ? 'Ничего не найдено' : 'Активных предупреждений нет'}</strong><span>{loading ? 'Лента появится после получения снимка.' : active.length > 0 ? 'Измените фильтр или номер борта.' : 'Новые предупреждения появятся здесь.'}</span></div>
      ) : (
        <div className="alerts-scroll" ref={scrollRef}>
          {visible.map((alert) => {
            const vehicle = vehicles.find((item) => item.tr_id === alert.tr_id)
            const selected = alert.alert_id === selectedAlertId && alert.tr_id === selectedTrId
            const risk = riskMeta(alert.risk)
            return (
              <button
                key={alert.alert_id}
                ref={selected ? selectedItemRef : undefined}
                className={`alert-item risk-${alert.risk}${selected ? ' selected' : ''}`}
                onClick={() => onSelect(alert.tr_id, alert.alert_id)}
                aria-pressed={selected}
                aria-label={`Событие ${alert.alert_id}: борт ${alert.tr_id}, ${risk.label.toLowerCase()}, ${formatDelay(alert.forecast.delay_pred_s)} к ${stopLabel(alert.forecast.target_stop_name, alert.forecast.target_stop_id)}, создано ${displayClock(alert.created_at)}`}
              >
                <div className="alert-item-top">
                  <span className={`risk-indicator risk-${alert.risk}`}><risk.icon size={13} /></span>
                  <span className="alert-vehicle">Борт {alert.tr_id}</span>
                  <ChevronRight size={16} className="alert-chevron" />
                </div>
                <div className="alert-delay">{formatDelay(alert.forecast.delay_pred_s)} <small>к {stopLabel(alert.forecast.target_stop_name, alert.forecast.target_stop_id)}</small></div>
                <div className="alert-item-bottom"><span>{alert.forecast.cause.text}</span><span>через {formatCountdown(secondsUntil(alert.forecast.target_time_plan, simTime))}</span></div>
                {vehicle?.stale && <span className="stale-tag">Данные устарели</span>}
              </button>
            )
          })}
          {riskFilter === 'all' && query.trim() === '' && filtered.length > 7 && <button className="alerts-more" type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? 'Свернуть список' : `Показать все · ещё ${filtered.length - 7} ${alertWord(filtered.length - 7)}`}</button>}
        </div>
      )}
      <div className="panel-footer"><span className={`live-dot${feed === 'live' ? '' : feed === 'degraded' ? ' is-degraded' : ' is-paused'}`} />{feed === 'live' ? 'Лента обновляется вслед за потоком' : feed === 'degraded' ? 'Телеметрии нет: прогнозы по расписанию' : 'Лента не обновляется: нет свежих данных'}<a className="mobile-map-jump" href="#vehicle-map">К карте</a></div>
    </aside>
  )
}
