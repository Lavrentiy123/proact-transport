import baseSnapshot from './snapshot.json'
import type { Alert, WsMessage } from '../types/contracts'

export type Scenario = 'normal' | 'empty' | 'many' | 'disconnected'

const base = baseSnapshot as WsMessage

function extraAlert(index: number): Alert {
  const vehicle = base.vehicles![index % base.vehicles!.length]
  const forecast = vehicle.forecast!
  return {
    alert_id: `demo-${index}-${vehicle.tr_id}`,
    created_at: base.sim_time,
    tr_id: vehicle.tr_id,
    risk: index % 3 === 0 ? 'red' : 'yellow',
    priority: 80 - index * 7,
    title: `Борт ${vehicle.tr_id}: прогноз ${Math.round(forecast.delay_pred_s)} с`,
    forecast,
    recommendation: null,
    status: 'active',
  }
}

export function scenarioSnapshot(scenario: Scenario): WsMessage {
  const snapshot = structuredClone(base)
  if (scenario === 'empty') {
    snapshot.vehicles = []
    snapshot.alerts = []
  }
  if (scenario === 'many') {
    snapshot.alerts = [...(snapshot.alerts ?? []), ...Array.from({ length: 9 }, (_, i) => extraAlert(i))]
  }
  if (scenario === 'disconnected') {
    snapshot.vehicles = snapshot.vehicles?.map((vehicle) => ({ ...vehicle, stale: true }))
    if (snapshot.status) snapshot.status.mode = 'DEGRADED'
  }
  return snapshot
}
