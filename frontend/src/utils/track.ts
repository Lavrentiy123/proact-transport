import type { TrackResponse } from '../types/contracts'
import { contractTimeUs } from './time'
import { validCoordinate } from './geo'

/** Schedules have minute precision, so neighbouring stops may share a plan time;
 * only a decreasing time makes the route unusable for the time-distance chart. */
export function planTimesOrdered(times: number[]): boolean {
  return times.every((time, index) => Number.isFinite(time) && (index === 0 || time >= times[index - 1]))
}

/** REST routes may include observations from after the displayed simulation time. */
export function trackAtTime(track: TrackResponse | null, simTime: string): TrackResponse | null {
  if (!track) return null
  const cutoff = contractTimeUs(simTime)
  if (!Number.isFinite(cutoff)) return { ...track, trail: [], stops: track.stops.filter((stop) => validCoordinate(stop.lon, stop.lat)).map((stop) => ({ ...stop, time_fact: null })) }
  return {
    ...track,
    trail: track.trail.filter(([time, lat, lon]) => contractTimeUs(time) <= cutoff && validCoordinate(lon, lat)),
    stops: track.stops.filter((stop) => validCoordinate(stop.lon, stop.lat)).map((stop) => ({
      ...stop,
      time_fact: stop.time_fact && contractTimeUs(stop.time_fact) <= cutoff ? stop.time_fact : null,
    })),
  }
}
