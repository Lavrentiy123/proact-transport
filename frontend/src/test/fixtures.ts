import baseSnapshot from '../data/snapshot.json'
import type { Alert, TrackResponse, WsMessage } from '../types/contracts'

export const base = baseSnapshot as WsMessage

export function copy<T>(value: T): T {
  return structuredClone(value)
}

/** Full frame (vehicles, alerts, status) with every clock set to `simTime`. */
export function frameAt(simTime: string, patch: Partial<WsMessage> = {}): WsMessage {
  const frame = copy(base)
  frame.sim_time = simTime
  if (frame.status) frame.status.sim_time = simTime
  return { ...frame, ...patch }
}

export function alertFor(trId: number, alertId: string, patch: Partial<Alert> = {}): Alert {
  const template = copy(base.alerts![0])
  return { ...template, alert_id: alertId, tr_id: trId, ...patch }
}

export function trackFor(trId: number): TrackResponse {
  return {
    tr_id: trId,
    stops: [{ stop_id: 1, name: 'A', lat: 55.7, lon: 37.6, seq: 1, time_plan: '2026-01-06T12:30:00', time_fact: null, time_forecast: null }],
    trail: [['2026-01-06T12:39:00', 55.7, 37.6]],
  }
}

export function jsonResponse(data: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => data } as Response
}

/** A fetch that never answers and rejects with the abort reason, like the browser does. */
export function hangingFetch(_input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return new Promise((_, reject) => {
    const signal = init?.signal
    if (signal?.aborted) reject(signal.reason)
    signal?.addEventListener('abort', () => reject(signal.reason), { once: true })
  })
}
