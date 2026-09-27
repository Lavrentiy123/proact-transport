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
const wsServer = new WebSocketServer({ noServer: true })
let tick = 0

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
    const track = mockTracks[Number(match[1])]
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
  for (const client of wsServer.clients) if (client.readyState === 1) client.send(JSON.stringify(snapshot))
}, 1000)

wsServer.on('connection', (client) => client.send(JSON.stringify({ ...base, status: { ...base.status, mode: 'LIVE' } })))
server.listen(port, () => console.log(`Frontend test stream: http://localhost:${port} · ${vehicleCount} vehicles · ${alertCount} alerts`))
process.on('SIGINT', () => { clearInterval(timer); wsServer.close(); server.close() })
