import http from 'node:http'
import { readFileSync } from 'node:fs'
import { WebSocketServer } from 'ws'
import { mockTracks } from '../src/data/mockTracks.ts'

const base = JSON.parse(readFileSync(new URL('../src/data/snapshot.json', import.meta.url), 'utf8'))
const port = 8000
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
  for (const client of wsServer.clients) if (client.readyState === 1) client.send(JSON.stringify(snapshot))
}, 1000)

wsServer.on('connection', (client) => client.send(JSON.stringify({ ...base, status: { ...base.status, mode: 'LIVE' } })))
server.listen(port, () => console.log(`Frontend test stream: http://localhost:${port}`))
process.on('SIGINT', () => { clearInterval(timer); wsServer.close(); server.close() })
