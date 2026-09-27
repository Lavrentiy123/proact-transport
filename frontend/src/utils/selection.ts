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

export interface Selection {
  trId: number | null
  alertId: string | null
  /** Automatic selection follows the stream only until the dispatcher picks something. */
  pickedByUser: boolean
}

export const emptySelection: Selection = { trId: null, alertId: null, pickedByUser: false }

function mostUrgentAlert(alerts: Alert[]): Alert | undefined {
  return alerts.filter((item) => item.status === 'active')
    .sort((a, b) => b.priority - a.priority || b.created_at.localeCompare(a.created_at))[0]
}

/** A vehicle picked by the dispatcher opens its most urgent active alert. */
export function pickVehicle(alerts: Alert[], trId: number): Selection {
  return { trId, alertId: topActiveAlert(alerts, trId)?.alert_id ?? null, pickedByUser: true }
}

/** A new live epoch keeps the vehicle only if it is still in the stream; its alert is chosen again. */
export function selectionAfterEpoch(selection: Selection, snapshot: Pick<WsMessage, 'vehicles' | 'alerts'>): Selection {
  return { ...selection, trId: selectionPresent(snapshot, selection.trId) ? selection.trId : null, alertId: null }
}

/**
 * Selection policy applied after every snapshot. `liveSnapshot` is null in the demo.
 * - A vehicle that left the live stream is deselected; if the dispatcher picked it, the card stays empty.
 * - Until the dispatcher picks something, the card follows the most urgent live alert, and a vehicle
 *   without an alert gives way as soon as an alert appears.
 * - A selected vehicle always shows its active alert, the most urgent one when the chosen alert is gone.
 * Returns the same object when nothing changes.
 */
export function nextAutoSelection(selection: Selection, alerts: Alert[], liveSnapshot: WsMessage | null): Selection {
  let next = selection
  if (liveSnapshot?.vehicles != null && next.trId != null && !selectionPresent(liveSnapshot, next.trId)) {
    next = { ...next, trId: null, alertId: null }
  }
  if (liveSnapshot?.vehicles && !next.pickedByUser) {
    const liveAlerts = liveSnapshot.alerts ?? []
    const top = mostUrgentAlert(liveAlerts)
    const keep = next.trId != null && (!top || topActiveAlert(liveAlerts, next.trId))
    const trId = top?.tr_id ?? liveSnapshot.vehicles.find((item) => item.forecast)?.tr_id
    if (!keep && trId != null && trId !== next.trId) next = { ...next, trId, alertId: top?.alert_id ?? null }
  }
  if (next.trId != null && !(next.alertId != null && alerts.some((item) => item.alert_id === next.alertId && item.tr_id === next.trId && item.status === 'active'))) {
    const alertId = topActiveAlert(alerts, next.trId)?.alert_id ?? null
    if (alertId !== next.alertId) next = { ...next, alertId }
  }
  return next
}

export function forecastForSelection(vehicle: VehicleState | undefined, alert: Alert | undefined): Forecast | null {
  return alert?.forecast ?? vehicle?.forecast ?? null
}
