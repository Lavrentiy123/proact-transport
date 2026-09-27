import { parseWsMessage, type ActionResponse, type HorizonMetrics, type TrackResponse, type WsMessage } from '../types/contracts'
import { contractTimeUs } from '../utils/time'

export type ConnectionState = 'connecting' | 'connected' | 'disconnected'

export const emptyLiveSnapshot: WsMessage = { type: 'snapshot', sim_time: '', vehicles: [], alerts: [], status: null }

export interface LiveFieldTimes { vehicles: number; alerts: number; status: number }
export const emptyLiveFieldTimes = (): LiveFieldTimes => ({ vehicles: Number.NEGATIVE_INFINITY, alerts: Number.NEGATIVE_INFINITY, status: Number.NEGATIVE_INFINITY })

/** A full snapshot this far behind the accepted positions is a replay rewind, not a late frame. */
const REWIND_THRESHOLD_US = 60_000_000

export function isVehicleSnapshot(message: WsMessage): boolean {
  return message.type === 'snapshot' && message.vehicles != null
}

/** replay --loop and POST /replay/control move the clock back without reopening the WebSocket. */
export function isRewind(message: WsMessage, times: LiveFieldTimes): boolean {
  return isVehicleSnapshot(message) && Number.isFinite(times.vehicles) &&
    contractTimeUs(message.sim_time) < times.vehicles - REWIND_THRESHOLD_US
}

/** A new WebSocket session can restart its simulation clock. The first frame
 * with vehicle positions establishes a new ordering epoch; optional alerts
 * and status received earlier on that same connection can be carried in. */
export function startLiveEpoch(message: WsMessage, buffered = emptyLiveSnapshot, bufferedTimes = emptyLiveFieldTimes()) {
  if (!isVehicleSnapshot(message)) throw new Error('A live epoch requires a vehicle snapshot')
  return mergeLiveFrame(buffered, message, bufferedTimes)
}

export function vehicleLagSeconds(snapshot: WsMessage, times: LiveFieldTimes): number | null {
  if (!snapshot.sim_time || !Number.isFinite(times.vehicles)) return null
  return Math.max(0, (contractTimeUs(snapshot.sim_time) - times.vehicles) / 1_000_000)
}

export function mergeWsMessage(previous: WsMessage, incoming: WsMessage): WsMessage {
  return {
    type: 'snapshot',
    sim_time: !previous.sim_time || contractTimeUs(incoming.sim_time) >= contractTimeUs(previous.sim_time) ? incoming.sim_time : previous.sim_time,
    vehicles: incoming.vehicles ?? previous.vehicles,
    alerts: incoming.alerts ?? previous.alerts,
    status: incoming.status ?? previous.status,
  }
}

/** Partial status and alert frames must not block a slightly older vehicle frame. */
export function mergeLiveFrame(previous: WsMessage, incoming: WsMessage, times: LiveFieldTimes) {
  const timestamp = contractTimeUs(incoming.sim_time)
  const acceptedVehicles = incoming.vehicles != null && timestamp >= times.vehicles
  const advancedVehicles = acceptedVehicles && timestamp > times.vehicles
  const acceptedAlerts = incoming.alerts != null && timestamp >= times.alerts
  const acceptedStatus = incoming.status != null && timestamp >= times.status
  const filtered: WsMessage = {
    type: incoming.type,
    sim_time: incoming.sim_time,
    vehicles: acceptedVehicles ? incoming.vehicles : undefined,
    alerts: acceptedAlerts ? incoming.alerts : undefined,
    status: acceptedStatus ? incoming.status : undefined,
  }
  return {
    snapshot: mergeWsMessage(previous, filtered),
    times: {
      vehicles: acceptedVehicles ? timestamp : times.vehicles,
      alerts: acceptedAlerts ? timestamp : times.alerts,
      status: acceptedStatus ? timestamp : times.status,
    },
    acceptedVehicles,
    advancedVehicles,
    acceptedAlerts,
  }
}

export function connectLive(
  onMessage: (message: WsMessage) => void,
  onConnection: (state: ConnectionState) => void,
): () => void {
  let closed = false
  let socket: WebSocket | null = null
  let retryTimer: number | null = null
  let attempt = 0

  function connect() {
    if (closed) return
    onConnection('connecting')
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const connection = new WebSocket(`${protocol}//${window.location.host}/ws/live`)
    socket = connection
    connection.onopen = () => { if (closed || socket !== connection) return; attempt = 0; onConnection('connected') }
    connection.onmessage = (event) => {
      if (closed || socket !== connection) return
      try {
        const message = parseWsMessage(JSON.parse(String(event.data)))
        if (message) onMessage(message)
      } catch { /* A malformed frame is ignored; the last valid snapshot stays visible. */ }
    }
    connection.onclose = () => {
      if (closed || socket !== connection) return
      onConnection('disconnected')
      attempt += 1
      retryTimer = window.setTimeout(connect, Math.min(10_000, 1000 * 2 ** (attempt - 1)))
    }
    connection.onerror = () => connection.close()
  }

  connect()
  return () => {
    closed = true
    if (retryTimer != null) window.clearTimeout(retryTimer)
    socket?.close()
  }
}

export async function fetchTrack(trId: number, signal: AbortSignal): Promise<TrackResponse> {
  const response = await fetch(`/api/v1/tracks/${encodeURIComponent(trId)}`, { signal })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const value: unknown = await response.json()
  if (typeof value !== 'object' || value == null) throw new Error('Некорректный ответ маршрута')
  const track = value as Partial<TrackResponse>
  if (track.tr_id !== trId || !Array.isArray(track.stops) || !Array.isArray(track.trail)) {
    throw new Error('Некорректный ответ маршрута')
  }
  const finite = (value: unknown) => typeof value === 'number' && Number.isFinite(value)
  const integer = (value: unknown) => finite(value) && Number.isSafeInteger(value)
  const validTime = (value: unknown) => typeof value === 'string' && Number.isFinite(contractTimeUs(value))
  const validStop = (stop: unknown) => typeof stop === 'object' && stop !== null &&
    integer((stop as { seq?: unknown }).seq) &&
    finite((stop as { lat?: unknown }).lat) &&
    finite((stop as { lon?: unknown }).lon) &&
    validTime((stop as { time_plan?: unknown }).time_plan) &&
    integer((stop as { stop_id?: unknown }).stop_id) &&
    typeof (stop as { name?: unknown }).name === 'string' &&
    ((stop as { time_fact?: unknown }).time_fact == null || validTime((stop as { time_fact?: unknown }).time_fact)) &&
    ((stop as { time_forecast?: unknown }).time_forecast == null || validTime((stop as { time_forecast?: unknown }).time_forecast))
  const validTrail = (item: unknown) => Array.isArray(item) && item.length === 3 &&
    validTime(item[0]) && finite(item[1]) && finite(item[2])
  if (!track.stops.every(validStop) || !track.trail.every(validTrail)) throw new Error('Некорректный ответ маршрута')
  return track as TrackResponse
}

/** Горизонт 10–15 минут и онлайн-MAE, которые backend считает по журналу прогнозов потока. */
export async function fetchHorizon(signal: AbortSignal): Promise<HorizonMetrics | null> {
  const response = await fetch('/api/v1/metrics/horizon', { signal })
  if (!response.ok) return null
  const value = await response.json() as Partial<HorizonMetrics>
  if (typeof value.forecasts_total !== 'number' || typeof value.share_lead_in_window !== 'number') return null
  return value as HorizonMetrics
}

/** Решение диспетчера по алерту: apply — отправить рекомендацию водителю, dismiss — отклонить. */
export async function postAction(alertId: string, action: 'apply' | 'dismiss'): Promise<ActionResponse> {
  const response = await fetch('/api/v1/actions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ alert_id: alertId, action }),
    signal: AbortSignal.timeout(8_000),
  })
  if (response.status === 409) throw new Error('алерт уже снят или решён')
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const value = await response.json() as Partial<ActionResponse>
  if (typeof value.alert_id !== 'string' || typeof value.status !== 'string' || typeof value.driver_message !== 'string') {
    throw new Error('Некорректный ответ на действие')
  }
  return value as ActionResponse
}
