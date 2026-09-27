import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createServer } from 'vite'

const vite = await createServer({
  configFile: false,
  root: process.cwd(),
  server: { middlewareMode: true },
  appType: 'custom',
})

try {
  const { parseWsMessage } = await vite.ssrLoadModule('/src/types/contracts.ts')
  const { mergeLiveFrame, mergeWsMessage, emptyLiveFieldTimes, emptyLiveSnapshot, vehicleLagSeconds, fetchTrack, isClockJump, isRewind, isVehicleSnapshot, startLiveEpoch } = await vite.ssrLoadModule('/src/data/liveTransport.ts')
  const { planTimesOrdered, trackAtTime } = await vite.ssrLoadModule('/src/utils/track.ts')
  const { describeDelay } = await vite.ssrLoadModule('/src/utils/format.ts')
  const { selectedAlert, forecastForSelection, selectionPresent, topActiveAlert } = await vite.ssrLoadModule('/src/utils/selection.ts')
  const base = JSON.parse(readFileSync(new URL('../src/data/snapshot.json', import.meta.url), 'utf8'))
  const copy = (value) => structuredClone(value)

  assert.ok(parseWsMessage(base), 'contract example parses')
  const invalidPosition = copy(base)
  invalidPosition.vehicles[0].lat = 95
  assert.ok(parseWsMessage(invalidPosition), 'out-of-range coordinate remains in source count')
  invalidPosition.vehicles[0].lat = null
  assert.equal(parseWsMessage(invalidPosition), null, 'missing numeric position rejects frame')
  const duplicate = copy(base)
  duplicate.vehicles.push(copy(duplicate.vehicles[0]))
  assert.equal(parseWsMessage(duplicate), null, 'duplicate tr_id rejects frame')
  const invalidProbability = copy(base)
  invalidProbability.vehicles[0].forecast.p_late = 1.2
  assert.equal(parseWsMessage(invalidProbability), null, 'probability beyond 0..1 rejects frame')
  const futureForecast = copy(base)
  futureForecast.vehicles[0].forecast.issued_at = '2026-01-06T13:00:00'
  const withoutFutureForecast = parseWsMessage(futureForecast)
  assert.ok(withoutFutureForecast, 'future vehicle forecast does not reject the frame')
  assert.equal(withoutFutureForecast.vehicles[0].forecast, null, 'future vehicle forecast is dropped')
  assert.equal(withoutFutureForecast.vehicles.length, base.vehicles.length, 'vehicle with a dropped forecast keeps its position')
  const futureAlert = copy(base)
  futureAlert.alerts[0].created_at = '2026-01-06T13:00:00'
  assert.equal(parseWsMessage(futureAlert).alerts.length, base.alerts.length - 1, 'future alert is dropped, the frame stays')
  const futureAlertForecast = copy(base)
  futureAlertForecast.alerts[0].forecast.issued_at = '2026-01-06T13:00:00'
  assert.equal(parseWsMessage(futureAlertForecast).alerts.length, base.alerts.length - 1, 'alert with a future forecast is dropped, the frame stays')
  const futureStatus = copy(base)
  futureStatus.status.sim_time = '2026-01-06T13:00:00'
  assert.equal(parseWsMessage(futureStatus), null, 'future nested system status rejects frame')
  const skewedStatus = copy(base)
  skewedStatus.status.sim_time = '2026-01-06T12:40:00.020000'
  assert.ok(parseWsMessage(skewedStatus), 'status computed milliseconds after the frame on a running clock is accepted')
  skewedStatus.status.sim_time = '2026-01-06T12:40:05'
  assert.ok(parseWsMessage(skewedStatus), 'at ×5 five simulated seconds are within two seconds of wall time')
  skewedStatus.status.sim_time = '2026-01-06T12:40:30'
  assert.equal(parseWsMessage(skewedStatus), null, 'status far ahead of the frame still rejects it')
  skewedStatus.status.replay_speed = 1
  skewedStatus.status.sim_time = '2026-01-06T12:40:03'
  assert.equal(parseWsMessage(skewedStatus), null, 'at ×1 the allowance is two simulated seconds')
  const realFrame = JSON.parse(readFileSync(new URL('./fixtures/ws_live_real.json', import.meta.url), 'utf8'))
  assert.ok(realFrame.status.sim_time > realFrame.sim_time, 'real backend frame has its status computed after the frame time')
  assert.ok(parseWsMessage(realFrame), 'real backend frame is accepted')
  const precise = copy(base)
  precise.sim_time = '2026-01-06T12:40:00.123456'
  assert.ok(parseWsMessage(precise), 'microsecond ISO timestamp parses')
  precise.sim_time = '2026-01-06T12:40:00+03:00'
  assert.equal(parseWsMessage(precise), null, 'timezone offset rejected by naive-Moscow frontend policy')

  const prior = copy(base)
  assert.equal(mergeWsMessage(prior, { type: 'snapshot', sim_time: prior.sim_time, vehicles: [], alerts: [] }).vehicles.length, 0, 'empty arrays clear positions')
  assert.equal(mergeWsMessage(prior, { type: 'status', sim_time: prior.sim_time, vehicles: null }).vehicles.length, prior.vehicles.length, 'null preserves positions')

  let state = mergeLiveFrame(emptyLiveSnapshot, { type: 'status', sim_time: '2026-01-06T12:40:01', status: base.status }, emptyLiveFieldTimes())
  state = mergeLiveFrame(state.snapshot, { type: 'snapshot', sim_time: '2026-01-06T12:40:00.123499', vehicles: base.vehicles }, state.times)
  assert.equal(state.acceptedVehicles, true, 'status T+1 does not block vehicles T')
  assert.equal(state.snapshot.vehicles.length, base.vehicles.length)
  assert.equal(state.snapshot.sim_time, '2026-01-06T12:40:01', 'display clock remains latest')
  let repeated = state
  for (let index = 0; index < 20; index++) {
    repeated = mergeLiveFrame(repeated.snapshot, { type: 'snapshot', sim_time: '2026-01-06T12:40:00.123499', vehicles: base.vehicles }, repeated.times)
    assert.equal(repeated.acceptedVehicles, true, 'same-time corrected snapshot may replace data')
    assert.equal(repeated.advancedVehicles, false, 'same-time replay does not refresh age')
    assert.equal(repeated.times.vehicles, state.times.vehicles, 'vehicle freshness timestamp does not advance')
  }
  const older = mergeLiveFrame(state.snapshot, { type: 'snapshot', sim_time: '2026-01-06T12:40:00.123400', vehicles: [] }, state.times)
  assert.equal(older.acceptedVehicles, false, 'older vehicle frame rejected within one millisecond')
  assert.equal(older.snapshot.vehicles.length, base.vehicles.length)
  const statusAhead = mergeLiveFrame(emptyLiveSnapshot, { type: 'status', sim_time: '2026-01-06T13:00:00', status: base.status }, emptyLiveFieldTimes())
  const fleetBehind = mergeLiveFrame(statusAhead.snapshot, { type: 'snapshot', sim_time: '2026-01-06T12:00:00', vehicles: base.vehicles }, statusAhead.times)
  assert.equal(vehicleLagSeconds(fleetBehind.snapshot, fleetBehind.times), 3600, 'old vehicle field remains visibly stale against status clock')

  const beforeRestart = copy(base)
  beforeRestart.sim_time = '2026-01-06T12:45:00'
  beforeRestart.status.sim_time = beforeRestart.sim_time
  const oldSession = mergeLiveFrame(emptyLiveSnapshot, beforeRestart, emptyLiveFieldTimes())
  const staleOnSameConnection = mergeLiveFrame(oldSession.snapshot, base, oldSession.times)
  assert.equal(staleOnSameConnection.acceptedVehicles, false, 'merge alone rejects an older full frame within one connection')
  assert.equal(staleOnSameConnection.snapshot.sim_time, beforeRestart.sim_time, 'merge alone keeps the same-connection clock monotonic')
  assert.equal(isRewind(base, oldSession.times), true, 'full frame minutes behind accepted positions is a replay rewind and starts a new epoch')
  assert.equal(isRewind({ ...base, sim_time: '2026-01-06T12:44:30' }, oldSession.times), false, 'frame less than a minute late is not a rewind')
  assert.equal(isRewind({ type: 'status', sim_time: base.sim_time, status: base.status }, oldSession.times), false, 'partial frame cannot trigger a rewind')
  assert.equal(isRewind(base, emptyLiveFieldTimes()), false, 'first frame of a session is not a rewind')
  assert.equal(isClockJump(base, oldSession.times), true, 'rewind is a clock jump')
  assert.equal(isClockJump({ ...base, sim_time: '2026-01-06T12:45:10' }, oldSession.times), false, 'regular replay step is not a clock jump')
  assert.equal(isClockJump({ ...base, sim_time: '2026-01-06T12:51:00' }, oldSession.times), true, 'replay/control jump ahead starts a new epoch')
  const afterRewind = startLiveEpoch(base)
  assert.equal(afterRewind.acceptedVehicles, true, 'rewound replay frame replaces positions')
  assert.equal(afterRewind.snapshot.sim_time, base.sim_time, 'rewound replay frame resets the display clock')
  assert.equal(isVehicleSnapshot({ type: 'status', sim_time: base.sim_time, status: base.status }), false, 'status frame cannot start new vehicle epoch')
  assert.throws(() => startLiveEpoch({ type: 'status', sim_time: base.sim_time, status: base.status }), 'partial reconnect frame cannot reset old snapshot')
  assert.equal(oldSession.snapshot.sim_time, beforeRestart.sim_time, 'cached snapshot remains available during reconnect')
  const restarted = startLiveEpoch(base)
  assert.equal(restarted.snapshot.sim_time, base.sim_time, 'first full frame of new connection resets simulation clock')
  assert.equal(restarted.acceptedVehicles, true, 'restarted vehicles replace previous epoch')
  assert.equal(restarted.times.vehicles, restarted.times.status, 'new epoch field clocks are reset together')
  const bufferedStatus = mergeLiveFrame(emptyLiveSnapshot, { type: 'status', sim_time: base.sim_time, status: base.status }, emptyLiveFieldTimes())
  const bufferedAlerts = mergeLiveFrame(bufferedStatus.snapshot, { type: 'alert', sim_time: base.sim_time, alerts: base.alerts }, bufferedStatus.times)
  const vehiclesOnly = { type: 'snapshot', sim_time: base.sim_time, vehicles: base.vehicles }
  assert.equal(isVehicleSnapshot(vehiclesOnly), true, 'vehicles-only snapshot can start new epoch')
  const partialRestart = startLiveEpoch(vehiclesOnly, bufferedAlerts.snapshot, bufferedAlerts.times)
  assert.equal(partialRestart.snapshot.vehicles.length, base.vehicles.length, 'vehicles-only reconnect frame refreshes positions')
  assert.equal(partialRestart.snapshot.alerts.length, base.alerts.length, 'earlier alert frame from new connection survives')
  assert.equal(partialRestart.snapshot.status.mode, base.status.mode, 'earlier status frame from new connection survives')
  const alertOnlyVehicle = 999999
  const alertOnly = { ...base.alerts[0], alert_id: 'alert-only-reconnect', tr_id: alertOnlyVehicle }
  const bufferedAlertOnly = mergeLiveFrame(emptyLiveSnapshot, { type: 'alert', sim_time: base.sim_time, alerts: [alertOnly] }, emptyLiveFieldTimes())
  const alertOnlyRestart = startLiveEpoch(vehiclesOnly, bufferedAlertOnly.snapshot, bufferedAlertOnly.times)
  assert.equal(selectionPresent(vehiclesOnly, alertOnlyVehicle), false, 'incoming vehicle-only frame does not contain selected alert')
  assert.equal(selectionPresent(alertOnlyRestart.snapshot, alertOnlyVehicle), true, 'selection retains buffered active alert from new connection')
  const laterAlerts = mergeLiveFrame(partialRestart.snapshot, { type: 'alert', sim_time: '2026-01-06T12:40:01', alerts: [] }, partialRestart.times)
  assert.equal(laterAlerts.snapshot.alerts.length, 0, 'later partial alert frame updates new epoch')
  const lateOldFrame = mergeLiveFrame(restarted.snapshot, { ...beforeRestart, sim_time: '2026-01-06T12:39:00' }, restarted.times)
  assert.equal(lateOldFrame.acceptedVehicles, false, 'same-connection older frame is still rejected after reset')

  const route = {
    tr_id: 1,
    stops: [{ stop_id: 1, name: 'A', lat: 55, lon: 37, seq: 1, time_plan: '2026-01-06T12:39:00', time_fact: '2026-01-06T12:40:00.123499', time_forecast: null }],
    trail: [
      ['2026-01-06T12:40:00.123400', 55, 37],
      ['2026-01-06T12:40:00.123499', 55.1, 37.1],
    ],
  }
  const asOf = trackAtTime(route, '2026-01-06T12:40:00.123400')
  assert.equal(asOf.trail.length, 1, 'future trail point within same millisecond is hidden')
  assert.equal(asOf.stops[0].time_fact, null, 'future stop fact is hidden')
  const dirtyRoute = { ...route, trail: [['2026-01-06T12:40:00.123400', 0, 0], ['2026-01-06T12:40:00.123400', 55, 37]] }
  assert.equal(trackAtTime(dirtyRoute, '2026-01-06T12:40:00.123400').trail.length, 1, 'invalid GPS point is hidden without losing route')
  const originalFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ ...dirtyRoute, stops: [{ ...dirtyRoute.stops[0], lat: 95 }] }), { status: 200 })
    const fetched = await fetchTrack(1, new AbortController().signal)
    assert.equal(fetched.stops.length, 1, 'REST route retains numerically valid stop outside geographic range')
    assert.equal(fetched.trail.length, 2, 'REST route retains numerically valid GPS for display filtering')
    assert.equal(trackAtTime(fetched, '2026-01-06T12:40:00.123400').trail.length, 1, 'display filter removes invalid GPS only')
  } finally {
    globalThis.fetch = originalFetch
  }
  assert.equal(planTimesOrdered([1, 2, 2, 3]), true, 'stops sharing a minute-precision plan time keep the Marey chart')
  assert.equal(planTimesOrdered([1, 3, 2]), false, 'decreasing plan times are rejected')
  assert.equal(planTimesOrdered([1, Number.NaN]), false, 'unparsed plan time is rejected')
  assert.equal(describeDelay(-60), 'Опережение 1:00')
  assert.equal(describeDelay(60), 'Опоздание 1:00')
  assert.equal(describeDelay(0), 'По графику')

  const vehicle = base.vehicles[0]
  const separateForecast = { ...vehicle.forecast, delay_pred_s: -60, risk: 'green' }
  const anotherAlert = { ...base.alerts[0], alert_id: 'other-event', forecast: separateForecast }
  assert.equal(forecastForSelection(vehicle, selectedAlert([base.alerts[0], anotherAlert], vehicle.tr_id, 'other-event')), separateForecast, 'explicit alert drives shared forecast')
  assert.equal(forecastForSelection(vehicle, selectedAlert([base.alerts[0], anotherAlert], vehicle.tr_id, null)), vehicle.forecast, 'without a chosen alert the vehicle forecast is shown')
  const urgent = { ...base.alerts[0], alert_id: 'urgent-event', priority: base.alerts[0].priority + 10 }
  const resolved = { ...base.alerts[0], alert_id: 'resolved-event', priority: base.alerts[0].priority + 50, status: 'resolved' }
  assert.equal(topActiveAlert([base.alerts[0], urgent, resolved], vehicle.tr_id)?.alert_id, 'urgent-event', 'vehicle picked on the map opens its most urgent active alert')
  assert.equal(topActiveAlert(base.alerts, 424242), undefined, 'vehicle without alerts opens no alert')

  console.log('Contract smoke passed')
} finally {
  await vite.close()
}
