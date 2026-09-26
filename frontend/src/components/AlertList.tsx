import { ArrowUpRight, BellRing, ChevronRight, TriangleAlert } from 'lucide-react'
import type { Alert, VehicleState } from '../types/contracts'
import { formatCountdown, formatDelay } from '../utils/format'
import { secondsUntil } from '../utils/time'

interface Props {
  alerts: Alert[]
  vehicles: VehicleState[]
  selectedTrId: number | null
  simTime: string
  onSelect: (trId: number) => void
}

const alertWord = (count: number) => ({
  zero: 'предупреждений', one: 'предупреждение', two: 'предупреждения',
  few: 'предупреждения', many: 'предупреждений', other: 'предупреждения',
})[new Intl.PluralRules('ru-RU').select(count)]

export default function AlertList({ alerts, vehicles, selectedTrId, simTime, onSelect }: Props) {
  const active = alerts.filter((alert) => alert.status === 'active').sort((a, b) => b.priority - a.priority)
  const visible = active.slice(0, 7)

  return (
    <aside className="panel alerts-panel" aria-label="Лента предупреждений">
      <div className="panel-heading">
        <div><span className="eyebrow">Очередь диспетчера</span><h2>Предупреждения</h2></div>
        <span className="count-badge">{active.length}</span>
      </div>
      <div className="alerts-subheading">По приоритету · прогноз на 10–15 минут</div>
      {visible.length === 0 ? (
        <div className="empty-panel"><BellRing size={28} /><strong>Активных алертов нет</strong><span>Новые предупреждения появятся здесь.</span></div>
      ) : (
        <div className="alerts-scroll">
          {visible.map((alert) => {
            const vehicle = vehicles.find((item) => item.tr_id === alert.tr_id)
            const selected = alert.tr_id === selectedTrId
            return (
              <button
                key={alert.alert_id}
                className={`alert-item risk-${alert.risk}${selected ? ' selected' : ''}`}
                onClick={() => onSelect(alert.tr_id)}
                aria-pressed={selected}
              >
                <div className="alert-item-top">
                  <span className={`risk-indicator risk-${alert.risk}`}>{alert.risk === 'red' ? <TriangleAlert size={13} /> : <ArrowUpRight size={13} />}</span>
                  <span className="alert-vehicle">Борт {alert.tr_id}</span>
                  <ChevronRight size={16} className="alert-chevron" />
                </div>
                <div className="alert-delay">{formatDelay(alert.forecast.delay_pred_s)} <small>к {alert.forecast.target_stop_name}</small></div>
                <div className="alert-item-bottom"><span>{alert.forecast.cause.text}</span><span>через {formatCountdown(secondsUntil(alert.forecast.target_time_plan, simTime))}</span></div>
                {vehicle?.stale && <span className="stale-tag">Данные устарели</span>}
              </button>
            )
          })}
          {active.length > 7 && <div className="alerts-more">Ещё {active.length - 7} {alertWord(active.length - 7)}</div>}
        </div>
      )}
      <div className="panel-footer"><span className="live-dot" />События обновляются по мере поступления данных</div>
    </aside>
  )
}
