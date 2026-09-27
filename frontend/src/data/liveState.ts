import type { DropReason, WsMessage } from '../types/contracts'
import { contractTimeUs } from '../utils/time'
import { emptyLiveFieldTimes, emptyLiveSnapshot, isClockJump, isVehicleSnapshot, mergeLiveFrame, startLiveEpoch, vehicleLagSeconds, type ConnectionState, type LiveFieldTimes } from './liveTransport'

/** Positions older than this, by stream clock or by wall time, are shown as stale. */
export const STALL_AFTER_S = 15
/** A connection without a vehicle snapshot for this long offers a way back to the demo. */
export const WAITING_TOO_LONG_MS = 5_000

export type LiveKind = 'idle' | 'connecting' | 'awaitingSnapshot' | 'live' | 'stalled' | 'disconnected'
/** `session` — first vehicle snapshot of a connection, `clock-jump` — replay rewind or jump ahead on the same connection. */
export type EpochReason = 'session' | 'clock-jump'

export interface LiveState {
  kind: LiveKind
  /** Last accepted snapshot; kept while reconnecting so the dispatcher sees it as stale. */
  snapshot: WsMessage | null
  fieldTimes: LiveFieldTimes
  /** Grows with every new ordering epoch and is never reset, so effects can follow it. */
  epoch: number
  epochReason: EpochReason | null
  /** Optional frames of a new connection collected until its first vehicle snapshot; null outside that wait. */
  pending: { snapshot: WsMessage; times: LiveFieldTimes } | null
  connectedAt: number | null
  lastVehicleFrameAt: number | null
  lastStreamAdvanceAt: number | null
  hasVehicleSnapshot: boolean
  hasAlertSnapshot: boolean
  droppedFrames: number
  lastDropReason: DropReason | null
  now: number
}

export type LiveEvent =
  | { type: 'connecting'; at: number }
  | { type: 'connected'; at: number }
  | { type: 'disconnected'; at: number }
  | { type: 'frame'; message: WsMessage; at: number }
  | { type: 'drop'; reason: DropReason; at: number }
  | { type: 'tick'; at: number }
  | { type: 'reset'; at: number }

export function initialLiveState(now: number, epoch = 0): LiveState {
  return {
    kind: 'idle', snapshot: null, fieldTimes: emptyLiveFieldTimes(), epoch, epochReason: null, pending: null,
    connectedAt: null, lastVehicleFrameAt: null, lastStreamAdvanceAt: null,
    hasVehicleSnapshot: false, hasAlertSnapshot: false, droppedFrames: 0, lastDropReason: null, now,
  }
}

export function selectLagS(state: LiveState): number {
  return vehicleLagSeconds(state.snapshot ?? emptyLiveSnapshot, state.fieldTimes) ?? 0
}

export function selectWallAgeS(state: LiveState): number {
  return state.lastVehicleFrameAt == null ? 0 : Math.max(0, (state.now - state.lastVehicleFrameAt) / 1000)
}

/** Seconds since the stream clock last moved forward (forecast age on the wall clock). */
export function selectStreamAgeS(state: LiveState): number {
  return state.lastStreamAdvanceAt == null ? 0 : Math.max(0, (state.now - state.lastStreamAdvanceAt) / 1000)
}

/** Positions are too old; also true while a new connection still waits for its first snapshot. */
export function selectStalled(state: LiveState): boolean {
  return selectLagS(state) > STALL_AFTER_S || selectWallAgeS(state) > STALL_AFTER_S
}

export function selectConnected(state: LiveState): boolean {
  return state.kind === 'live'
}

export function selectConnection(state: LiveState): ConnectionState {
  return state.kind === 'disconnected' ? 'disconnected' : state.kind === 'idle' || state.kind === 'connecting' ? 'connecting' : 'connected'
}

export function selectWaitingTooLong(state: LiveState): boolean {
  return state.kind === 'awaitingSnapshot' && state.connectedAt != null && state.now - state.connectedAt >= WAITING_TOO_LONG_MS
}

/** Only a connection with fresh positions is live; the stall detector then decides between live and stalled. */
function settle(state: LiveState, positionsFresh = state.kind === 'live' || state.kind === 'stalled'): LiveState {
  const connected = state.kind === 'awaitingSnapshot' || state.kind === 'live' || state.kind === 'stalled'
  const kind: LiveKind = !connected ? state.kind : !positionsFresh ? 'awaitingSnapshot' : selectStalled(state) ? 'stalled' : 'live'
  return kind === state.kind ? state : { ...state, kind }
}

function acceptFrame(state: LiveState, message: WsMessage, at: number): LiveState {
  const pending = state.pending
  if (pending && !isVehicleSnapshot(message)) {
    // Keep the prior session visible as stale while collecting optional
    // fields from the new connection. They are never merged into it.
    const buffered = mergeLiveFrame(pending.snapshot, message, pending.times)
    return { ...state, pending: { snapshot: buffered.snapshot, times: buffered.times } }
  }
  // A replay clock jump on the same connection resets backend alerts, so it
  // starts a new epoch exactly like a reconnect does.
  const clockJump = !pending && isClockJump(message, state.fieldTimes)
  const newEpoch = pending != null || clockJump
  const previous = state.snapshot ?? emptyLiveSnapshot
  const previousTime = newEpoch ? '' : previous.sim_time
  const result = newEpoch
    ? startLiveEpoch(message, pending?.snapshot ?? emptyLiveSnapshot, pending?.times ?? emptyLiveFieldTimes())
    : mergeLiveFrame(previous, message, state.fieldTimes)
  const advancedStream = !previousTime || contractTimeUs(result.snapshot.sim_time) > contractTimeUs(previousTime)
  const next: LiveState = {
    ...state,
    snapshot: result.snapshot,
    fieldTimes: result.times,
    pending: newEpoch ? null : state.pending,
    epoch: newEpoch ? state.epoch + 1 : state.epoch,
    epochReason: newEpoch ? clockJump ? 'clock-jump' : 'session' : state.epochReason,
    lastStreamAdvanceAt: advancedStream ? at : state.lastStreamAdvanceAt,
    hasVehicleSnapshot: state.hasVehicleSnapshot || result.acceptedVehicles,
    hasAlertSnapshot: (newEpoch ? Number.isFinite(result.times.alerts) : state.hasAlertSnapshot) || result.acceptedAlerts,
    lastVehicleFrameAt: result.advancedVehicles ? at : state.lastVehicleFrameAt,
  }
  return settle(next, result.advancedVehicles || state.kind === 'live' || state.kind === 'stalled')
}

export function liveReducer(state: LiveState, event: LiveEvent): LiveState {
  const now = event.at
  switch (event.type) {
    case 'connecting':
      return { ...state, now, kind: 'connecting', connectedAt: null }
    case 'connected':
      return { ...state, now, kind: 'awaitingSnapshot', connectedAt: now, pending: { snapshot: emptyLiveSnapshot, times: emptyLiveFieldTimes() } }
    case 'disconnected':
      return { ...state, now, kind: 'disconnected', connectedAt: null }
    case 'frame':
      return acceptFrame({ ...state, now }, event.message, now)
    case 'drop':
      return { ...state, now, droppedFrames: state.droppedFrames + 1, lastDropReason: event.reason }
    case 'tick':
      return settle({ ...state, now })
    case 'reset':
      return initialLiveState(now, state.epoch)
  }
}
