import { describe, expect, it } from 'vitest'
import { base, copy, frameAt } from '../test/fixtures'
import { parseWsFrame, parseWsMessage, type WsMessage } from '../types/contracts'
import {
  initialLiveState, liveReducer, selectConnected, selectConnection, selectLagS, selectStalled, selectStreamAgeS,
  selectWaitingTooLong, selectWallAgeS, type LiveEvent, type LiveState,
} from './liveState'

const T0 = 1_000_000

function run(state: LiveState, ...events: LiveEvent[]): LiveState {
  return events.reduce(liveReducer, state)
}

const frame = (message: WsMessage, at: number): LiveEvent => ({ type: 'frame', message, at })

/** Connected and showing the first full snapshot at 12:45:00. */
function liveAt(simTime = '2026-01-06T12:45:00', at = T0): LiveState {
  return run(initialLiveState(at), { type: 'connecting', at }, { type: 'connected', at }, frame(frameAt(simTime), at))
}

describe('liveReducer: connection', () => {
  it('goes connecting → awaitingSnapshot → live with the first vehicle snapshot', () => {
    let state = initialLiveState(T0)
    expect(state.kind).toBe('idle')
    state = liveReducer(state, { type: 'connecting', at: T0 })
    expect(state.kind).toBe('connecting')
    expect(selectConnection(state)).toBe('connecting')
    state = liveReducer(state, { type: 'connected', at: T0 + 100 })
    expect(state.kind).toBe('awaitingSnapshot')
    expect(state.connectedAt).toBe(T0 + 100)
    expect(selectConnection(state)).toBe('connected')
    expect(selectConnected(state)).toBe(false)
    state = liveReducer(state, frame(frameAt(base.sim_time), T0 + 200))
    expect(state.kind).toBe('live')
    expect(selectConnected(state)).toBe(true)
    expect(state.epoch).toBe(1)
    expect(state.epochReason).toBe('session')
    expect(state.hasVehicleSnapshot).toBe(true)
    expect(state.hasAlertSnapshot).toBe(true)
    expect(state.lastVehicleFrameAt).toBe(T0 + 200)
    expect(state.snapshot?.vehicles).toHaveLength(base.vehicles!.length)
  })

  it('buffers partial frames of a new connection until the first vehicle snapshot', () => {
    let state = run(initialLiveState(T0), { type: 'connecting', at: T0 }, { type: 'connected', at: T0 })
    state = liveReducer(state, frame({ type: 'alert', sim_time: base.sim_time, alerts: base.alerts }, T0 + 10))
    state = liveReducer(state, frame({ type: 'status', sim_time: base.sim_time, status: base.status }, T0 + 20))
    expect(state.kind).toBe('awaitingSnapshot')
    expect(state.snapshot).toBeNull()
    expect(state.hasAlertSnapshot).toBe(false)
    expect(state.epoch).toBe(0)
    state = liveReducer(state, frame({ type: 'snapshot', sim_time: base.sim_time, vehicles: base.vehicles }, T0 + 30))
    expect(state.kind).toBe('live')
    expect(state.snapshot?.alerts).toHaveLength(base.alerts!.length)
    expect(state.snapshot?.status?.mode).toBe(base.status!.mode)
    expect(state.hasAlertSnapshot).toBe(true)
    expect(state.pending).toBeNull()
  })

  it('never merges partial frames of a new connection into the previous session', () => {
    let state = liveAt()
    state = run(state, { type: 'disconnected', at: T0 + 1000 }, { type: 'connecting', at: T0 + 2000 }, { type: 'connected', at: T0 + 3000 })
    state = liveReducer(state, frame({ type: 'alert', sim_time: '2026-01-06T12:45:05', alerts: [] }, T0 + 3100))
    expect(state.snapshot?.alerts).toHaveLength(base.alerts!.length)
    expect(state.kind).toBe('awaitingSnapshot')
  })

  it('keeps the last snapshot while disconnected', () => {
    const before = liveAt()
    const state = liveReducer(before, { type: 'disconnected', at: T0 + 500 })
    expect(state.kind).toBe('disconnected')
    expect(selectConnection(state)).toBe('disconnected')
    expect(selectConnected(state)).toBe(false)
    expect(state.snapshot).toBe(before.snapshot)
    expect(state.hasVehicleSnapshot).toBe(true)
  })

  it('starts a session epoch on reconnect even when the clock restarted', () => {
    let state = liveAt('2026-01-06T12:45:00')
    state = run(state, { type: 'disconnected', at: T0 + 1000 }, { type: 'connecting', at: T0 + 2000 }, { type: 'connected', at: T0 + 3000 })
    state = liveReducer(state, frame(frameAt('2026-01-06T12:40:00'), T0 + 4000))
    expect(state.kind).toBe('live')
    expect(state.epoch).toBe(2)
    expect(state.epochReason).toBe('session')
    expect(state.snapshot?.sim_time).toBe('2026-01-06T12:40:00')
  })

  it('reports waiting too long 5 s after connect without a snapshot', () => {
    let state = run(initialLiveState(T0), { type: 'connecting', at: T0 }, { type: 'connected', at: T0 })
    state = liveReducer(state, { type: 'tick', at: T0 + 4999 })
    expect(selectWaitingTooLong(state)).toBe(false)
    state = liveReducer(state, { type: 'tick', at: T0 + 5000 })
    expect(selectWaitingTooLong(state)).toBe(true)
    state = liveReducer(state, frame(frameAt(base.sim_time), T0 + 5100))
    expect(selectWaitingTooLong(state)).toBe(false)
  })

  it('reset returns to idle and keeps the epoch counter growing', () => {
    const state = liveReducer(liveAt(), { type: 'reset', at: T0 + 10 })
    expect(state.kind).toBe('idle')
    expect(state.snapshot).toBeNull()
    expect(state.epoch).toBe(1)
    expect(state.hasVehicleSnapshot).toBe(false)
  })
})

describe('liveReducer: stall detector', () => {
  it('stalls 15 s of wall time after the last advancing vehicle frame and recovers on the next one', () => {
    let state = liveAt('2026-01-06T12:45:00', T0)
    state = liveReducer(state, { type: 'tick', at: T0 + 15_000 })
    expect(state.kind).toBe('live')
    state = liveReducer(state, { type: 'tick', at: T0 + 15_001 })
    expect(state.kind).toBe('stalled')
    expect(selectStalled(state)).toBe(true)
    expect(selectConnected(state)).toBe(false)
    expect(selectWallAgeS(state)).toBeCloseTo(15.001)
    state = liveReducer(state, frame(frameAt('2026-01-06T12:45:05'), T0 + 16_000))
    expect(state.kind).toBe('live')
    expect(selectWallAgeS(state)).toBe(0)
  })

  it('a repeated frame with the same time does not refresh positions', () => {
    let state = liveAt('2026-01-06T12:45:00', T0)
    state = liveReducer(state, frame(frameAt('2026-01-06T12:45:00'), T0 + 10_000))
    expect(state.lastVehicleFrameAt).toBe(T0)
    state = liveReducer(state, { type: 'tick', at: T0 + 16_000 })
    expect(state.kind).toBe('stalled')
  })

  it('stalls when positions lag the stream clock by more than 15 s', () => {
    let state = liveAt('2026-01-06T12:45:00', T0)
    state = liveReducer(state, frame({ type: 'status', sim_time: '2026-01-06T12:45:16', status: { ...base.status!, sim_time: '2026-01-06T12:45:16' } }, T0 + 1000))
    expect(selectLagS(state)).toBe(16)
    expect(state.kind).toBe('stalled')
    expect(selectStreamAgeS(state)).toBe(0)
  })
})

describe('liveReducer: clock jumps', () => {
  it('a rewind of more than 60 s on the same connection is a clock-jump epoch', () => {
    let state = liveAt('2026-01-06T12:45:00')
    const outcomeEpoch = state.epoch
    state = liveReducer(state, frame(frameAt('2026-01-06T12:43:59'), T0 + 1000))
    expect(state.epoch).toBe(outcomeEpoch + 1)
    expect(state.epochReason).toBe('clock-jump')
    expect(state.snapshot?.sim_time).toBe('2026-01-06T12:43:59')
    expect(state.kind).toBe('live')
  })

  it('a frame less than a minute late is rejected without a new epoch', () => {
    let state = liveAt('2026-01-06T12:45:00')
    state = liveReducer(state, frame(frameAt('2026-01-06T12:44:30', { vehicles: [] }), T0 + 1000))
    expect(state.epoch).toBe(1)
    expect(state.snapshot?.vehicles).toHaveLength(base.vehicles!.length)
    expect(state.snapshot?.sim_time).toBe('2026-01-06T12:45:00')
  })

  it('a jump ahead of more than 5 min is a clock-jump epoch, a regular step is not', () => {
    let state = liveAt('2026-01-06T12:45:00')
    state = liveReducer(state, frame(frameAt('2026-01-06T12:49:59'), T0 + 1000))
    expect(state.epoch).toBe(1)
    state = liveReducer(state, frame(frameAt('2026-01-06T12:55:00'), T0 + 2000))
    expect(state.epoch).toBe(2)
    expect(state.epochReason).toBe('clock-jump')
  })

  it('a partial frame cannot trigger a clock jump', () => {
    let state = liveAt('2026-01-06T12:45:00')
    state = liveReducer(state, frame({ type: 'status', sim_time: '2026-01-06T12:00:00', status: { ...base.status!, sim_time: '2026-01-06T12:00:00' } }, T0 + 1000))
    expect(state.epoch).toBe(1)
  })
})

describe('liveReducer: dropped frames (BL-32)', () => {
  it('counts drops and remembers the last reason without touching the snapshot', () => {
    const before = liveAt()
    let state = liveReducer(before, { type: 'drop', reason: 'json', at: T0 + 1 })
    state = liveReducer(state, { type: 'drop', reason: 'status-ahead', at: T0 + 2 })
    expect(state.droppedFrames).toBe(2)
    expect(state.lastDropReason).toBe('status-ahead')
    expect(state.snapshot).toBe(before.snapshot)
    expect(state.kind).toBe('live')
  })
})

describe('parseWsFrame', () => {
  it('accepts the contract example and keeps parseWsMessage compatible', () => {
    expect(parseWsFrame(base)).toHaveProperty('message')
    expect(parseWsMessage(base)).not.toBeNull()
    expect(parseWsMessage({ type: 'nope' })).toBeNull()
  })

  it.each([
    ['envelope', () => ({ ...copy(base), type: 'nope' })],
    ['envelope', () => ({ ...copy(base), sim_time: '2026-01-06T12:40:00+03:00' })],
    ['vehicle', () => { const value = copy(base); (value.vehicles![0] as { lat: unknown }).lat = null; return value }],
    ['duplicate', () => { const value = copy(base); value.vehicles!.push(copy(value.vehicles![0])); return value }],
    ['alert', () => { const value = copy(base); value.alerts![0].forecast.p_late = 1.5; return value }],
    ['duplicate', () => { const value = copy(base); value.alerts!.push(copy(value.alerts![0])); return value }],
    ['status', () => { const value = copy(base); (value.status as { mode: string }).mode = 'BROKEN'; return value }],
    ['status-ahead', () => { const value = copy(base); value.status!.sim_time = '2026-01-06T12:41:00'; return value }],
  ])('rejects with reason %s', (reason, make) => {
    expect(parseWsFrame(make())).toEqual({ reason })
  })
})
