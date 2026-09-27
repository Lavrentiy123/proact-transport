import { useEffect, useMemo, useState } from 'react'
import type { TrackResponse, VehicleState } from '../types/contracts'
import { fetchTrack, REQUEST_TIMEOUT_MS, timeoutSignal } from './liveTransport'

export const NETWORK_REFRESH_MS = 60_000
export const NETWORK_MAX_VEHICLES = 60
export const NETWORK_CONCURRENCY = 6

/** Route network: planned stops of up to 60 vehicles, 6 requests at a time; vehicles without a schedule are skipped. */
export function useRouteNetwork(enabled: boolean, vehicles: VehicleState[] | null | undefined) {
  const [tracks, setTracks] = useState<Record<number, TrackResponse>>({})
  const vehicleIds = useMemo(
    () => (vehicles ?? []).map((item) => item.tr_id).sort((a, b) => a - b).slice(0, NETWORK_MAX_VEHICLES).join(','),
    [vehicles],
  )

  useEffect(() => {
    if (!enabled || !vehicleIds) { setTracks({}); return }
    const controller = new AbortController()
    const ids = vehicleIds.split(',').map(Number)
    // With 8 s per request a slow pass can outlast the refresh period; the next pass waits for it.
    let running = false
    const load = async () => {
      if (running) return
      running = true
      try {
        const loaded: Record<number, TrackResponse> = {}
        for (let index = 0; index < ids.length; index += NETWORK_CONCURRENCY) {
          const batch = await Promise.all(ids.slice(index, index + NETWORK_CONCURRENCY).map((id) => {
            const timeout = timeoutSignal(REQUEST_TIMEOUT_MS, controller.signal)
            return fetchTrack(id, timeout.signal).then((value) => [id, value] as const).catch(() => null).finally(timeout.dispose)
          }))
          if (controller.signal.aborted) return
          for (const entry of batch) if (entry) loaded[entry[0]] = entry[1]
        }
        // Backend unreachable (every request failed): keep the last known network on the map.
        if (Object.keys(loaded).length > 0) setTracks(loaded)
      } finally {
        running = false
      }
    }
    void load()
    const timer = window.setInterval(() => { void load() }, NETWORK_REFRESH_MS)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [enabled, vehicleIds])

  return tracks
}
