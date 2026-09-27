import { useEffect, useReducer } from 'react'
import { dropReasonText } from '../types/contracts'
import { connectLive } from './liveTransport'
import { initialLiveState, liveReducer, selectConnected, selectConnection, selectLagS, selectStalled, selectStreamAgeS, selectWaitingTooLong, selectWallAgeS } from './liveState'

const TICK_MS = 1000

/** Live WebSocket stream as a state machine: connection, epochs, stall detector and dropped frames. */
export function useLiveStream(enabled: boolean) {
  const [state, dispatch] = useReducer(liveReducer, undefined, () => initialLiveState(Date.now()))

  useEffect(() => {
    if (!enabled) return
    // Callbacks of a previous source session are ignored after cleanup.
    let active = true
    const disconnect = connectLive(
      (message) => { if (active) dispatch({ type: 'frame', message, at: Date.now() }) },
      (connection) => { if (active) dispatch({ type: connection, at: Date.now() }) },
      (reason) => { if (active) dispatch({ type: 'drop', reason, at: Date.now() }) },
    )
    const timer = window.setInterval(() => dispatch({ type: 'tick', at: Date.now() }), TICK_MS)
    return () => {
      active = false
      window.clearInterval(timer)
      disconnect()
      dispatch({ type: 'reset', at: Date.now() })
    }
  }, [enabled])

  return {
    state,
    snapshot: state.snapshot,
    connection: selectConnection(state),
    connected: selectConnected(state),
    stalled: selectStalled(state),
    waitingTooLong: selectWaitingTooLong(state),
    lagS: selectLagS(state),
    wallAgeS: selectWallAgeS(state),
    streamAgeS: selectStreamAgeS(state),
    droppedFrames: state.droppedFrames,
    lastDropReason: state.lastDropReason ? dropReasonText[state.lastDropReason] : null,
  }
}
