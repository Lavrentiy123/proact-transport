import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { alertFor, base, hangingFetch, jsonResponse, trackFor } from '../test/fixtures'
import { useDispatcherActions } from './useDispatcherActions'
import { useLiveStream } from './useLiveStream'
import { NETWORK_CONCURRENCY, NETWORK_REFRESH_MS, useRouteNetwork } from './useRouteNetwork'
import { TRACK_REFRESH_MS, useSelectedTrack } from './useSelectedTrack'

const trackUrl = (input: RequestInfo | URL) => Number(String(input).split('/').at(-1))

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

describe('useSelectedTrack', () => {
  it('loads the track of the selected vehicle', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => jsonResponse(trackFor(trackUrl(input)))))
    const { result } = renderHook(() => useSelectedTrack(true, 131672, 1))
    expect(result.current.loading).toBe(true)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.track?.tr_id).toBe(131672)
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBe(false)
  })

  it('reports a first load that does not answer in 8 s', async () => {
    vi.stubGlobal('fetch', vi.fn(hangingFetch))
    const { result } = renderHook(() => useSelectedTrack(true, 131672, 1))
    await act(async () => { await vi.advanceTimersByTimeAsync(7_999) })
    expect(result.current.error).toBe(false)
    expect(result.current.loading).toBe(true)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(result.current.error).toBe(true)
    expect(result.current.loading).toBe(false)
  })

  it('a failed refresh keeps the last good track without an error', async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => jsonResponse(trackFor(trackUrl(input))))
    vi.stubGlobal('fetch', fetch)
    const { result } = renderHook(() => useSelectedTrack(true, 131672, 1))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    fetch.mockImplementation(async () => jsonResponse({ detail: 'boom' }, 500))
    await act(async () => { await vi.advanceTimersByTimeAsync(TRACK_REFRESH_MS) })
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(result.current.track?.tr_id).toBe(131672)
    expect(result.current.error).toBe(false)
  })

  it('drops a late answer for the previously selected vehicle', async () => {
    const answers = new Map<number, (value: Response) => void>()
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => new Promise<Response>((resolve) => { answers.set(trackUrl(input), resolve) })))
    const { result, rerender } = renderHook(({ trId }) => useSelectedTrack(true, trId, 1), { initialProps: { trId: 131672 } })
    rerender({ trId: 122658 })
    await act(async () => {
      answers.get(131672)?.(jsonResponse(trackFor(131672)))
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(result.current.track).toBeNull()
    expect(result.current.loading).toBe(true)
    await act(async () => {
      answers.get(122658)?.(jsonResponse(trackFor(122658)))
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(result.current.track?.tr_id).toBe(122658)
  })

  it('a new epoch reloads the track from scratch', async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => jsonResponse(trackFor(trackUrl(input))))
    vi.stubGlobal('fetch', fetch)
    const { result, rerender } = renderHook(({ epoch }) => useSelectedTrack(true, 131672, epoch), { initialProps: { epoch: 1 } })
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    rerender({ epoch: 2 })
    expect(result.current.track).toBeNull()
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(result.current.track?.tr_id).toBe(131672)
  })

  it('does nothing when disabled', () => {
    const fetch = vi.fn(hangingFetch)
    vi.stubGlobal('fetch', fetch)
    const { result } = renderHook(() => useSelectedTrack(false, 131672, 1))
    expect(fetch).not.toHaveBeenCalled()
    expect(result.current).toEqual({ track: null, loading: false, error: false })
  })
})

describe('useDispatcherActions', () => {
  const target = base.alerts![0]

  it('stores the driver reply from POST /api/v1/actions', async () => {
    const fetch = vi.fn(async () => jsonResponse({ alert_id: target.alert_id, status: 'applied', driver_message: 'Диспетчер: держать 24 км/ч', driver_reply: 'успеваю' }))
    vi.stubGlobal('fetch', fetch)
    const { result } = renderHook(() => useDispatcherActions('live'))
    await act(async () => { await result.current.act(target, 'apply') })
    expect(fetch).toHaveBeenCalledWith('/api/v1/actions', expect.objectContaining({ method: 'POST', body: JSON.stringify({ alert_id: target.alert_id, action: 'apply' }) }))
    expect(result.current.outcomes[target.tr_id]).toMatchObject({ status: 'applied', driver_reply: 'успеваю' })
  })

  it('409 means the alert is already resolved', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'alert is not active' }, 409)))
    const { result } = renderHook(() => useDispatcherActions('live'))
    await act(async () => { await result.current.act(target, 'dismiss') })
    expect(result.current.outcomes[target.tr_id]).toEqual({ alert_id: target.alert_id, error: 'алерт уже снят или решён' })
  })

  it('gives up after 8 s without an answer', async () => {
    vi.stubGlobal('fetch', vi.fn(hangingFetch))
    const { result } = renderHook(() => useDispatcherActions('live'))
    let pending: Promise<void> = Promise.resolve()
    act(() => { pending = result.current.act(target, 'apply') })
    await act(async () => { await vi.advanceTimersByTimeAsync(8_000); await pending })
    expect(result.current.outcomes[target.tr_id]).toEqual({ alert_id: target.alert_id, error: 'нет ответа 8 секунд' })
  })

  it('ignores a late answer after the session was reset', async () => {
    let answer: (value: Response) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { answer = resolve })))
    const { result } = renderHook(() => useDispatcherActions('live'))
    let pending: Promise<void> = Promise.resolve()
    act(() => { pending = result.current.act(target, 'apply') })
    act(() => { result.current.reset() })
    await act(async () => {
      answer(jsonResponse({ alert_id: target.alert_id, status: 'applied', driver_message: 'x', driver_reply: null }))
      await pending
    })
    expect(result.current.outcomes).toEqual({})
  })

  it('emulates the driver in the demo without a request', async () => {
    const fetch = vi.fn(hangingFetch)
    vi.stubGlobal('fetch', fetch)
    const { result } = renderHook(() => useDispatcherActions('demo'))
    await act(async () => { await result.current.act(target, 'apply') })
    expect(fetch).not.toHaveBeenCalled()
    expect(result.current.outcomes[target.tr_id]).toMatchObject({ status: 'applied', driver_reply: 'успеваю' })
  })
})

describe('useRouteNetwork', () => {
  const fleet = (count: number) => Array.from({ length: count }, (_, index) => ({ ...base.vehicles![0], tr_id: 1000 + index }))

  it('loads in batches of 6 and ends a request that does not answer in 8 s', async () => {
    const vehicles = fleet(14)
    let inFlight = 0
    let maxInFlight = 0
    const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      inFlight += 1
      maxInFlight = Math.max(maxInFlight, inFlight)
      if (trackUrl(input) === 1003) return hangingFetch(input, init).finally(() => { inFlight -= 1 })
      inFlight -= 1
      return Promise.resolve(jsonResponse(trackFor(trackUrl(input))))
    })
    vi.stubGlobal('fetch', fetch)
    const { result } = renderHook(() => useRouteNetwork(true, vehicles))
    expect(fetch).toHaveBeenCalledTimes(NETWORK_CONCURRENCY)
    await act(async () => { await vi.advanceTimersByTimeAsync(7_999) })
    expect(fetch).toHaveBeenCalledTimes(NETWORK_CONCURRENCY)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(fetch).toHaveBeenCalledTimes(vehicles.length)
    expect(maxInFlight).toBeLessThanOrEqual(NETWORK_CONCURRENCY)
    expect(Object.keys(result.current).map(Number)).not.toContain(1003)
    expect(Object.keys(result.current)).toHaveLength(vehicles.length - 1)
  })

  it('skips a refresh while the previous slow pass is still running', async () => {
    // 60 vehicles that never answer: 10 batches × 8 s outlast the 60 s refresh period.
    const fetch = vi.fn(hangingFetch)
    vi.stubGlobal('fetch', fetch)
    renderHook(() => useRouteNetwork(true, fleet(60)))
    await act(async () => { await vi.advanceTimersByTimeAsync(NETWORK_REFRESH_MS) })
    // Batches started at 0, 8, …, 56 s; an overlapping pass would add six more at 60 s.
    expect(fetch).toHaveBeenCalledTimes(8 * NETWORK_CONCURRENCY)
  })
})

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(readonly url: string) { FakeWebSocket.instances.push(this) }
  close() { this.onclose?.() }
}

describe('useLiveStream', () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  it('connects, shows the snapshot, counts dropped frames and reconnects', async () => {
    const { result, rerender } = renderHook(({ enabled }) => useLiveStream(enabled), { initialProps: { enabled: true } })
    const socket = FakeWebSocket.instances[0]
    expect(socket.url).toMatch(/\/ws\/live$/)
    expect(result.current.connection).toBe('connecting')
    act(() => { socket.onopen?.() })
    expect(result.current.state.kind).toBe('awaitingSnapshot')
    act(() => { socket.onmessage?.({ data: JSON.stringify(base) }) })
    expect(result.current.connected).toBe(true)
    expect(result.current.snapshot?.vehicles).toHaveLength(base.vehicles!.length)
    act(() => {
      socket.onmessage?.({ data: '{"type":"snapshot","sim_time":' })
      socket.onmessage?.({ data: JSON.stringify({ ...base, alerts: [alertFor(1, 'a'), alertFor(1, 'a')] }) })
    })
    expect(result.current.droppedFrames).toBe(2)
    expect(result.current.lastDropReason).toBe('повтор tr_id или alert_id в кадре')
    expect(result.current.connected).toBe(true)

    act(() => { socket.close() })
    expect(result.current.connection).toBe('disconnected')
    expect(result.current.snapshot?.vehicles).toHaveLength(base.vehicles!.length)
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(result.current.connection).toBe('connecting')

    rerender({ enabled: false })
    expect(result.current.state.kind).toBe('idle')
    expect(result.current.snapshot).toBeNull()
  })

  it('stalls after 15 s without new positions', async () => {
    const { result } = renderHook(() => useLiveStream(true))
    const socket = FakeWebSocket.instances[0]
    act(() => { socket.onopen?.(); socket.onmessage?.({ data: JSON.stringify(base) }) })
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })
    expect(result.current.connected).toBe(true)
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000) })
    expect(result.current.stalled).toBe(true)
    expect(result.current.state.kind).toBe('stalled')
  })
})
