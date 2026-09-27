import http from 'node:http'
import { readFileSync } from 'node:fs'
import { WebSocketServer } from 'ws'
import { mockTracks } from '../src/data/mockTracks.ts'

const base = JSON.parse(readFileSync(new URL('../src/data/snapshot.json', import.meta.url), 'utf8'))
const allowedVehicleCounts = new Set([0, 1, 3, 100, 500, 1000])
const vehicleCount = Number(process.env.STUB_VEHICLES ?? 3)
if (!allowedVehicleCounts.has(vehicleCount)) throw new Error('STUB_VEHICLES must be 0, 1, 3, 100, 500 or 1000')
const alertCount = Number(process.env.STUB_ALERTS ?? (vehicleCount === 3 ? base.alerts.length : Math.min(vehicleCount, Math.ceil(vehicleCount / 10))))
if (!Number.isSafeInteger(alertCount) || alertCount < 0 || alertCount > 1000) throw new Error('STUB_ALERTS must be an integer from 0 to 1000')

if (vehicleCount !== 3) {
  const templates = base.vehicles
  base.vehicles = Array.from({ length: vehicleCount }, (_, index) => {
    const vehicle = structuredClone(templates[index % templates.length])
    vehicle.tr_id = 200000 + index
    vehicle.lat = index % 20 === 0 && vehicleCount >= 100 ? 95 : 55.55 + Math.floor(index / 40) * 0.006
    vehicle.lon = 37.35 + (index % 40) * 0.014
    if (index % 5 === 4) vehicle.forecast = null
    return vehicle
  })
  base.alerts = []
}
if (alertCount !== base.alerts.length) {
  base.alerts = Array.from({ length: alertCount }, (_, index) => {
    const vehicle = base.vehicles[index % Math.max(base.vehicles.length, 1)]
    const forecast = vehicle?.forecast ?? base.vehicles.find((item) => item.forecast)?.forecast ?? JSON.parse(readFileSync(new URL('../src/data/snapshot.json', import.meta.url), 'utf8')).vehicles[0].forecast
    return {
      alert_id: `load-${index}`, created_at: base.sim_time, tr_id: vehicle?.tr_id ?? 200000 + index,
      risk: forecast.risk, priority: 1000 - index, title: `Борт ${vehicle?.tr_id ?? 200000 + index}: тестовое предупреждение`,
      forecast, recommendation: null, status: 'active',
    }
  })
}
const port = Number(process.env.STUB_PORT ?? 8000)
if (!Number.isSafeInteger(port) || port < 1 || port > 65535) throw new Error('STUB_PORT must be a valid TCP port')
const stubCase = process.env.STUB_CASE ?? 'normal'
const allowedCases = new Set(['normal', 'bad-frame', 'track-race', 'track-500', 'track-timeout', 'drop-selected', 'partial-alert', 'partial-status', 'partial-both', 'slow-first', 'long-track'])
if (!allowedCases.has(stubCase)) throw new Error(`STUB_CASE must be one of: ${[...allowedCases].join(', ')}`)
const targetTrId = Number(process.env.STUB_TR_ID ?? 131672)
if (!Number.isSafeInteger(targetTrId)) throw new Error('STUB_TR_ID must be an integer')
const triggerTick = Number(process.env.STUB_TRIGGER_TICK ?? (stubCase === 'drop-selected' || stubCase === 'slow-first' ? 5 : 3))
if (!Number.isSafeInteger(triggerTick) || triggerTick < 1) throw new Error('STUB_TRIGGER_TICK must be a positive integer')
const delayMs = Number(process.env.STUB_DELAY_MS ?? (stubCase === 'track-timeout' ? 9000 : 3500))
if (!Number.isSafeInteger(delayMs) || delayMs < 0 || delayMs > 60000) throw new Error('STUB_DELAY_MS must be 0..60000')
if (stubCase === 'track-timeout' && delayMs <= 8000) throw new Error('track-timeout requires STUB_DELAY_MS > 8000')
if (stubCase === 'track-race' && delayMs >= 8000) throw new Error('track-race requires STUB_DELAY_MS < 8000')
if (['track-race', 'track-500', 'track-timeout'].includes(stubCase) && !mockTracks[targetTrId]) throw new Error('STUB_TR_ID needs a mock track for this case')
if (['track-race', 'track-500', 'track-timeout'].includes(stubCase) && !base.vehicles.some((item) => item.tr_id === targetTrId)) throw new Error('STUB_TR_ID needs a vehicle in the stub snapshot')
if (stubCase === 'drop-selected' && !base.vehicles.some((item) => item.tr_id === targetTrId)) throw new Error('STUB_TR_ID needs a vehicle in the stub snapshot')
let longTrack = null
if (stubCase === 'long-track') {
  const original = mockTracks[131672]
  const forecast = base.vehicles.find((item) => item.tr_id === 131672)?.forecast
  if (!forecast) throw new Error('long-track requires the default 3-vehicle snapshot')
  const first = original.stops[0]
  const target = original.stops.at(-1)
  const firstMs = Date.parse(`${first.time_plan}Z`)
  const targetMs = Date.parse(`${forecast.target_time_plan}Z`)
  longTrack = { tr_id: 131672, trail: original.trail, stops: Array.from({ length: 35 }, (_, index) => {
    if (index === 0) return { ...first }
    const fraction = index / 34
    return {
      stop_id: index === 34 ? forecast.target_stop_id : first.stop_id + 1000 + index,
      name: index === 34 ? forecast.target_stop_name : `Промежуточная остановка ${index}`,
      lat: Number((first.lat + (target.lat - first.lat) * fraction).toFixed(6)),
      lon: Number((first.lon + (target.lon - first.lon) * fraction).toFixed(6)),
      seq: index + 1,
      time_plan: new Date(firstMs + Math.round((targetMs - firstMs) * fraction)).toISOString().slice(0, 19),
      time_fact: null,
      time_forecast: null,
    }
  }) }
}
const wsServer = new WebSocketServer({ noServer: true })
const clientTicks = new WeakMap()
let tick = 0
let latestSnapshot = base

function sendJson(response, code, data) {
  response.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' })
  response.end(JSON.stringify(data))
}

const server = http.createServer((request, response) => {
  const path = new URL(request.url ?? '/', 'http://localhost').pathname
  if (path === '/health') return sendJson(response, 200, { ok: true })
  if (path === '/api/v1/vehicles') return sendJson(response, 200, base.vehicles)
  if (path === '/api/v1/alerts') return sendJson(response, 200, base.alerts)
  if (path === '/api/v1/system/status') return sendJson(response, 200, base.status)
  const match = /^\/api\/v1\/tracks\/(\d+)$/.exec(path)
  if (match) {
    const trId = Number(match[1])
    const track = stubCase === 'long-track' && trId === 131672 ? longTrack : mockTracks[trId]
    if (trId === targetTrId && stubCase === 'track-500') return sendJson(response, 500, { detail: 'stub track failure' })
    if (trId === targetTrId && ['track-race', 'track-timeout'].includes(stubCase)) {
      setTimeout(() => { if (!response.destroyed) sendJson(response, track ? 200 : 404, track ?? { detail: 'not found' }) }, delayMs)
      return
    }
    return sendJson(response, track ? 200 : 404, track ?? { detail: 'not found' })
  }
  sendJson(response, 404, { detail: 'not found' })
})

server.on('upgrade', (request, socket, head) => {
  if (request.url !== '/ws/live') return socket.destroy()
  wsServer.handleUpgrade(request, socket, head, (client) => wsServer.emit('connection', client))
})

const timer = setInterval(() => {
  tick += 1
  const snapshot = structuredClone(base)
  const simTime = new Date(Date.parse(`${base.sim_time}Z`) + tick * 5000).toISOString().slice(0, 19)
  snapshot.sim_time = simTime
  snapshot.status.sim_time = simTime
  snapshot.status.mode = 'LIVE'
  snapshot.vehicles.forEach((vehicle, index) => {
    if (vehicle.lat <= 90) vehicle.lon += Math.sin(tick / 5 + index) * 0.0001
  })
  latestSnapshot = snapshot
  for (const client of wsServer.clients) {
    if (client.readyState !== 1) continue
    const clientTick = (clientTicks.get(client) ?? 0) + 1
    clientTicks.set(client, clientTick)
    if (stubCase === 'slow-first' && clientTick <= triggerTick) continue
    if (stubCase === 'bad-frame' && clientTick === triggerTick) {
      client.send('{"type":"snapshot","sim_time":')
      continue
    }
    if (clientTick === triggerTick && stubCase.startsWith('partial-')) {
      if (stubCase !== 'partial-status') client.send(JSON.stringify({ type: 'alert', sim_time: simTime, alerts: snapshot.alerts }))
      if (stubCase !== 'partial-alert') client.send(JSON.stringify({ type: 'status', sim_time: simTime, status: snapshot.status }))
      continue
    }
    if (stubCase === 'drop-selected' && clientTick >= triggerTick) {
      client.send(JSON.stringify({ ...snapshot,
        vehicles: snapshot.vehicles.filter((item) => item.tr_id !== targetTrId),
        alerts: snapshot.alerts.filter((item) => item.tr_id !== targetTrId),
      }))
      continue
    }
    client.send(JSON.stringify(snapshot))
  }
}, 1000)

wsServer.on('connection', (client) => {
  clientTicks.set(client, 0)
  if (stubCase !== 'slow-first') client.send(JSON.stringify({ ...latestSnapshot, status: { ...latestSnapshot.status, mode: 'LIVE' } }))
})
server.listen(port, () => console.log(`Frontend test stream: http://localhost:${port} · ${vehicleCount} vehicles · ${alertCount} alerts · case ${stubCase}`))
process.on('SIGINT', () => { clearInterval(timer); wsServer.close(); server.close() })
