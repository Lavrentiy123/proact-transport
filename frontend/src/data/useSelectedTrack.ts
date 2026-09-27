import { useEffect, useState } from 'react'
import type { TrackResponse } from '../types/contracts'
import { fetchTrack, isAbort, REQUEST_TIMEOUT_MS, timeoutSignal } from './liveTransport'

export const TRACK_REFRESH_MS = 15_000

/** Track of the selected vehicle: loaded on selection and refreshed so the trail follows the stream. */
export function useSelectedTrack(enabled: boolean, trId: number | null, epoch: number) {
  const [track, setTrack] = useState<TrackResponse | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!enabled || trId == null) {
      if (!enabled) setTrack(null)
      setLoading(false)
      setError(false)
      return
    }
    // Every run is its own generation: a response after a new vehicle, epoch or source is dropped.
    let active = true
    let controller: AbortController | null = null
    const load = (initial: boolean) => {
      controller?.abort()
      const current = new AbortController()
      controller = current
      const timeout = timeoutSignal(REQUEST_TIMEOUT_MS, current.signal)
      if (initial) {
        setTrack(null)
        setError(false)
        setLoading(true)
      }
      fetchTrack(trId, timeout.signal)
        .then((next) => { if (active) { setTrack(next); setError(false) } })
        // A failed refresh keeps the last good route; only a failed first load is reported.
        .catch((reason: unknown) => { if (initial && active && !isAbort(reason)) setError(true) })
        .finally(() => { timeout.dispose(); if (initial && active) setLoading(false) })
    }
    load(true)
    const timer = window.setInterval(() => load(false), TRACK_REFRESH_MS)
    return () => { active = false; window.clearInterval(timer); controller?.abort() }
  }, [enabled, trId, epoch])

  return {
    track: enabled && track?.tr_id === trId ? track : null,
    loading: enabled && loading,
    error: enabled && error,
  }
}
