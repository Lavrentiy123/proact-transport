import type { Alert, Forecast, VehicleState, WsMessage } from '../types/contracts'

export function selectionPresent(snapshot: Pick<WsMessage, 'vehicles' | 'alerts'>, trId: number | null): boolean {
  return trId != null && Boolean(
    snapshot.vehicles?.some((item) => item.tr_id === trId) ||
    snapshot.alerts?.some((item) => item.tr_id === trId && item.status === 'active'),
  )
}

export function selectedAlert(alerts: Alert[], trId: number | null, alertId: string | null): Alert | undefined {
  if (trId == null || alertId == null) return undefined
  return alerts.find((item) => item.alert_id === alertId && item.tr_id === trId && item.status === 'active')
}

/** A vehicle picked on the map or in the list opens its most urgent active alert. */
export function topActiveAlert(alerts: Alert[], trId: number): Alert | undefined {
  return alerts
    .filter((item) => item.tr_id === trId && item.status === 'active')
    .sort((a, b) => b.priority - a.priority || b.created_at.localeCompare(a.created_at) || a.alert_id.localeCompare(b.alert_id))[0]
}

export function forecastForSelection(vehicle: VehicleState | undefined, alert: Alert | undefined): Forecast | null {
  return alert?.forecast ?? vehicle?.forecast ?? null
}
