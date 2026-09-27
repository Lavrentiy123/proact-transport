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

export interface AxisTick { x: number; text: string }

/** Chooses time-axis labels by their pixel extent: centred boxes of `labelWidth` stay at least `minGap` apart,
 * a clock text appears once, and `keep` (first, last, target stop) wins over its neighbours. */
export function pickAxisLabels(ticks: AxisTick[], labelWidth: number, minGap: number, keep: number[] = []): number[] {
  const spacing = labelWidth + minGap
  const chosen: number[] = []
  const texts = new Set<string>()
  const fits = (index: number) => !texts.has(ticks[index].text) && chosen.every((other) => Math.abs(ticks[other].x - ticks[index].x) >= spacing)
  const order = [...keep.filter((index) => index >= 0 && index < ticks.length), ...ticks.map((_, index) => index)]
  for (const index of order) {
    if (!Number.isFinite(ticks[index].x) || !fits(index)) continue
    chosen.push(index)
    texts.add(ticks[index].text)
  }
  return chosen.sort((a, b) => a - b)
}
