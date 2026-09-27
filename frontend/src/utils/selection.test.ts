import { describe, expect, it } from 'vitest'
import { alertFor, base, copy, frameAt } from '../test/fixtures'
import type { WsMessage } from '../types/contracts'
import { emptySelection, nextAutoSelection, pickVehicle, selectionAfterEpoch, type Selection } from './selection'

const [red, yellow, green] = base.vehicles!.map((item) => item.tr_id)
const baseAlert = base.alerts![0]

function liveFrame(patch: Partial<WsMessage> = {}): WsMessage {
  return frameAt(base.sim_time, patch)
}

/** Applies the policy until it settles, as the App effect does over renders. */
function settle(selection: Selection, snapshot: WsMessage | null, alerts = snapshot?.alerts ?? []): Selection {
  let current = selection
  for (let step = 0; step < 5; step++) {
    const next = nextAutoSelection(current, alerts, snapshot)
    if (next === current) return current
    current = next
  }
  throw new Error('selection policy does not settle')
}

describe('nextAutoSelection', () => {
  it('opens the most urgent live alert while the dispatcher has picked nothing', () => {
    const urgent = alertFor(yellow, 'urgent', { priority: baseAlert.priority + 5 })
    const snapshot = liveFrame({ alerts: [baseAlert, urgent] })
    expect(settle(emptySelection, snapshot)).toEqual({ trId: yellow, alertId: 'urgent', pickedByUser: false })
  })

  it('without alerts opens the first vehicle with a forecast', () => {
    const snapshot = liveFrame({ alerts: [] })
    expect(settle(emptySelection, snapshot)).toEqual({ trId: red, alertId: null, pickedByUser: false })
  })

  it('an automatic vehicle without an alert gives way as soon as an alert appears', () => {
    const selection: Selection = { trId: green, alertId: null, pickedByUser: false }
    expect(settle(selection, liveFrame({ alerts: [] }))).toBe(selection)
    expect(settle(selection, liveFrame({ alerts: [baseAlert] }))).toEqual({ trId: red, alertId: baseAlert.alert_id, pickedByUser: false })
  })

  it('an automatic vehicle with its own alert is kept when a more urgent one appears elsewhere', () => {
    const own = alertFor(yellow, 'own', { priority: 10 })
    const selection: Selection = { trId: yellow, alertId: 'own', pickedByUser: false }
    expect(settle(selection, liveFrame({ alerts: [baseAlert, own] }))).toBe(selection)
  })

  it('never overrides a vehicle picked by the dispatcher', () => {
    const selection: Selection = { trId: green, alertId: null, pickedByUser: true }
    expect(settle(selection, liveFrame({ alerts: [baseAlert] }))).toBe(selection)
  })

  it('a picked vehicle that left the stream leaves the card empty', () => {
    const selection: Selection = { trId: red, alertId: baseAlert.alert_id, pickedByUser: true }
    const snapshot = liveFrame({ vehicles: base.vehicles!.filter((item) => item.tr_id !== red), alerts: [alertFor(yellow, 'other')] })
    expect(settle(selection, snapshot)).toEqual({ trId: null, alertId: null, pickedByUser: true })
  })

  it('an automatic vehicle that left the stream is replaced by the most urgent remaining alert', () => {
    const selection: Selection = { trId: red, alertId: baseAlert.alert_id, pickedByUser: false }
    const snapshot = liveFrame({ vehicles: base.vehicles!.filter((item) => item.tr_id !== red), alerts: [alertFor(yellow, 'other')] })
    expect(settle(selection, snapshot)).toEqual({ trId: yellow, alertId: 'other', pickedByUser: false })
  })

  it('a vehicle kept only by its active alert stays selected', () => {
    const selection: Selection = { trId: 999, alertId: 'only-alert', pickedByUser: true }
    const snapshot = liveFrame({ alerts: [alertFor(999, 'only-alert')] })
    expect(settle(selection, snapshot)).toBe(selection)
  })

  it('switches to the next active alert of the selected vehicle when its alert is resolved', () => {
    const second = alertFor(red, 'second', { priority: 20 })
    const selection: Selection = { trId: red, alertId: baseAlert.alert_id, pickedByUser: true }
    const resolved = { ...baseAlert, status: 'resolved' }
    expect(settle(selection, liveFrame({ alerts: [resolved, second] }))).toEqual({ ...selection, alertId: 'second' })
    expect(settle(selection, liveFrame({ alerts: [resolved] }))).toEqual({ ...selection, alertId: null })
  })

  it('in the demo only keeps the alert of the selected vehicle in sync', () => {
    const demo = copy(base)
    const selection: Selection = { trId: green, alertId: null, pickedByUser: false }
    expect(settle(selection, null, demo.alerts!)).toBe(selection)
    expect(settle({ trId: red, alertId: null, pickedByUser: false }, null, demo.alerts!)).toEqual({ trId: red, alertId: baseAlert.alert_id, pickedByUser: false })
  })

  it('before the first live snapshot nothing is selected', () => {
    expect(nextAutoSelection(emptySelection, [], null)).toBe(emptySelection)
  })
})

describe('pickVehicle and selectionAfterEpoch', () => {
  it('a vehicle picked on the map or in the list opens its most urgent active alert', () => {
    const urgent = alertFor(red, 'urgent', { priority: baseAlert.priority + 1 })
    expect(pickVehicle([baseAlert, urgent], red)).toEqual({ trId: red, alertId: 'urgent', pickedByUser: true })
    expect(pickVehicle([baseAlert], green)).toEqual({ trId: green, alertId: null, pickedByUser: true })
  })

  it('a new epoch keeps a vehicle still in the stream and chooses its alert again', () => {
    const selection: Selection = { trId: red, alertId: 'old', pickedByUser: true }
    expect(selectionAfterEpoch(selection, liveFrame())).toEqual({ trId: red, alertId: null, pickedByUser: true })
    expect(selectionAfterEpoch(selection, liveFrame({ vehicles: [], alerts: [] }))).toEqual({ trId: null, alertId: null, pickedByUser: true })
  })
})
