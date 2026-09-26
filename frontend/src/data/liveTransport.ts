import { parseWsMessage, type TrackResponse, type WsMessage } from '../types/contracts'

export type ConnectionState = 'connecting' | 'connected' | 'disconnected'

export const emptyLiveSnapshot: WsMessage = { type: 'snapshot', sim_time: '', vehicles: [], alerts: [], status: null }

export function mergeWsMessage(previous: WsMessage, incoming: WsMessage): WsMessage {
  return {
    type: 'snapshot',
    sim_time: incoming.sim_time || previous.sim_time,
    vehicles: incoming.vehicles ?? previous.vehicles,
    alerts: incoming.alerts ?? previous.alerts,
    status: incoming.status ?? previous.status,
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
    socket = new WebSocket(`${protocol}//${window.location.host}/ws/live`)
    socket.onopen = () => { attempt = 0; onConnection('connected') }
    socket.onmessage = (event) => {
      try {
        const message = parseWsMessage(JSON.parse(String(event.data)))
        if (message) onMessage(message)
      } catch { /* A malformed frame is ignored; the last valid snapshot stays visible. */ }
    }
    socket.onclose = () => {
      if (closed) return
      onConnection('disconnected')
      attempt += 1
      retryTimer = window.setTimeout(connect, Math.min(10_000, 1000 * 2 ** (attempt - 1)))
    }
    socket.onerror = () => socket?.close()
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
  const validStop = (stop: unknown) => typeof stop === 'object' && stop !== null &&
    typeof (stop as { seq?: unknown }).seq === 'number' &&
    typeof (stop as { lat?: unknown }).lat === 'number' &&
    typeof (stop as { lon?: unknown }).lon === 'number' &&
    typeof (stop as { time_plan?: unknown }).time_plan === 'string' &&
    typeof (stop as { stop_id?: unknown }).stop_id === 'number'
  const validTrail = (item: unknown) => Array.isArray(item) && item.length === 3 &&
    typeof item[0] === 'string' && typeof item[1] === 'number' && typeof item[2] === 'number'
  if (!track.stops.every(validStop) || !track.trail.every(validTrail)) throw new Error('Некорректный ответ маршрута')
  return track as TrackResponse
}
