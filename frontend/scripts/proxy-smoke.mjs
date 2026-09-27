import assert from 'node:assert/strict'
import WebSocket from 'ws'

const origin = process.env.SMOKE_ORIGIN ?? 'http://localhost:3000'

async function jsonAt(path) {
  const response = await fetch(new URL(path, origin))
  assert.equal(response.status, 200, `${path}: expected HTTP 200`)
  return response.json()
}

const vehicles = await jsonAt('/api/v1/vehicles')
assert.ok(Array.isArray(vehicles) && vehicles.some((vehicle) => vehicle.tr_id === 131672), 'REST vehicle proxy')
const track = await jsonAt('/api/v1/tracks/131672')
assert.equal(track.tr_id, 131672, 'REST track proxy')
assert.ok(Array.isArray(track.stops) && track.stops.length > 0, 'REST track stops')

const wsUrl = new URL('/ws/live', origin)
wsUrl.protocol = wsUrl.protocol === 'https:' ? 'wss:' : 'ws:'
await new Promise((resolve, reject) => {
  const socket = new WebSocket(wsUrl)
  const timeout = setTimeout(() => {
    socket.terminate()
    reject(new Error('WS proxy did not deliver a snapshot within 8 seconds'))
  }, 8000)
  const fail = (error) => {
    clearTimeout(timeout)
    socket.terminate()
    reject(error)
  }
  socket.once('error', fail)
  socket.once('unexpected-response', (_request, response) => fail(new Error(`WS proxy returned HTTP ${response.statusCode}`)))
  socket.once('upgrade', (response) => {
    if (response.statusCode !== 101) fail(new Error(`WS proxy expected HTTP 101, got ${response.statusCode}`))
  })
  socket.once('message', (data) => {
    try {
      const frame = JSON.parse(data.toString())
      assert.equal(frame.type, 'snapshot', 'WS frame type')
      assert.ok(Array.isArray(frame.vehicles) && frame.vehicles.some((vehicle) => vehicle.tr_id === 131672), 'WS snapshot vehicles')
      clearTimeout(timeout)
      socket.close()
      resolve()
    } catch (error) {
      fail(error)
    }
  })
})

console.log('Nginx REST and WebSocket proxy smoke passed')
