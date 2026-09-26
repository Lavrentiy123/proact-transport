import type { Alert, TrackResponse, VehicleState, WsMessage } from '../types/contracts'
import { mockTracks } from './mockTracks'
import { scenarioSnapshot, type Scenario } from './scenarios'
import { advanceContractTime } from '../utils/time'

export const REPLAY_DURATION_S = 180

function moveVehicle(vehicle: VehicleState, elapsedSeconds: number): VehicleState {
  if (vehicle.stale || elapsedSeconds === 0) return vehicle
  const stops = mockTracks[vehicle.tr_id]?.stops ?? []
  const destination = stops.at(-1)
  if (!destination) return vehicle
  const progress = Math.min(elapsedSeconds / 420, 0.42)
  return {
    ...vehicle,
    lat: vehicle.lat + (destination.lat - vehicle.lat) * progress,
    lon: vehicle.lon + (destination.lon - vehicle.lon) * progress,
  }
}

/** A deterministic, deliberately synthetic timeline for a backend-free pitch. */
export function replaySnapshot(scenario: Scenario, elapsedSeconds: number): WsMessage {
  const snapshot = scenarioSnapshot(scenario)
  const elapsed = Math.max(0, Math.min(elapsedSeconds, REPLAY_DURATION_S))
  const simTime = advanceContractTime(snapshot.sim_time, elapsed)
  snapshot.sim_time = simTime
  if (snapshot.status) snapshot.status.sim_time = simTime
  snapshot.vehicles = snapshot.vehicles?.map((vehicle) => moveVehicle(vehicle, elapsed)) ?? []

  // The second warning arrives 45 simulated seconds after the base frame.
  if (scenario !== 'empty' && elapsed >= 45) {
    const vehicle = snapshot.vehicles.find((item) => item.tr_id === 122658)
    if (vehicle?.forecast && !snapshot.alerts?.some((item) => item.alert_id === 'demo-122658-event')) {
      const event: Alert = {
        alert_id: 'demo-122658-event', created_at: advanceContractTime(simTime, -(elapsed - 45)),
        tr_id: vehicle.tr_id, risk: 'yellow', priority: 65,
        title: `Борт ${vehicle.tr_id}: прогноз отклонения к ост. «${vehicle.forecast.target_stop_name}»`,
        forecast: vehicle.forecast, recommendation: null, status: 'active',
      }
      snapshot.alerts = [...(snapshot.alerts ?? []), event]
    }
  }
  return snapshot
}

export function replayTrack(trId: number | null, snapshot: WsMessage, source: 'demo' | 'live'): TrackResponse | null {
  if (trId == null || source !== 'demo') return null
  const track = mockTracks[trId]
  const vehicle = snapshot.vehicles?.find((item) => item.tr_id === trId)
  if (!track || !vehicle || vehicle.stale) return track ?? null
  const last = track.trail.at(-1)
  const trail = last && (last[1] !== vehicle.lat || last[2] !== vehicle.lon)
    ? [...track.trail, [snapshot.sim_time, vehicle.lat, vehicle.lon] as [string, number, number]]
    : track.trail
  return { ...track, trail }
}
