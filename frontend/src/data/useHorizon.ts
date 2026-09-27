import { useEffect, useState } from 'react'
import type { HorizonMetrics } from '../types/contracts'
import { fetchHorizon, REQUEST_TIMEOUT_MS, timeoutSignal } from './liveTransport'

export const HORIZON_REFRESH_MS = 10_000

/** Horizon 10–15 min and online MAE from the stream forecast log. */
export function useHorizon(enabled: boolean) {
  const [horizon, setHorizon] = useState<HorizonMetrics | null>(null)

  useEffect(() => {
    if (!enabled) { setHorizon(null); return }
    const controller = new AbortController()
    const load = () => {
      const timeout = timeoutSignal(REQUEST_TIMEOUT_MS, controller.signal)
      return fetchHorizon(timeout.signal)
        .then((value) => { if (!controller.signal.aborted) setHorizon(value) })
        .catch(() => { /* панель просто не обновится */ })
        .finally(timeout.dispose)
    }
    void load()
    const timer = window.setInterval(() => { void load() }, HORIZON_REFRESH_MS)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [enabled])

  return horizon
}
