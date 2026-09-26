import { useEffect, useMemo, useState } from 'react'
import { SignalZero } from 'lucide-react'
import AlertList from './components/AlertList'
import IncidentCard from './components/IncidentCard'
import MareyChart from './components/MareyChart'
import StatusBar from './components/StatusBar'
import VehicleMap from './components/VehicleMap'
import { connectLive, emptyLiveSnapshot, fetchTrack, mergeWsMessage, type ConnectionState } from './data/liveTransport'
import { replaySnapshot, replayTrack, REPLAY_DURATION_S } from './data/replay'
import type { Scenario } from './data/scenarios'
import type { TrackResponse, WsMessage } from './types/contracts'

export default function App() {
  const [source, setSource] = useState<'demo' | 'live'>('demo')
  const [scenario, setScenario] = useState<Scenario>('normal')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [selectedTrId, setSelectedTrId] = useState<number | null>(131672)
  const [playing, setPlaying] = useState(true)
  const [liveSnapshot, setLiveSnapshot] = useState<WsMessage | null>(null)
  const [liveConnection, setLiveConnection] = useState<ConnectionState>('disconnected')
  const [liveTrack, setLiveTrack] = useState<TrackResponse | null>(null)
  const [trackError, setTrackError] = useState(false)

  const demoSnapshot = useMemo(() => replaySnapshot(scenario, elapsedSeconds), [scenario, elapsedSeconds])
  const snapshot = source === 'demo' ? demoSnapshot : liveSnapshot ?? emptyLiveSnapshot
  const connected = source === 'demo' ? scenario !== 'disconnected' : liveConnection === 'connected'
  const vehicles = source === 'live' && !connected
    ? (snapshot.vehicles ?? []).map((item) => ({ ...item, stale: true }))
    : snapshot.vehicles ?? []
  const alerts = snapshot.alerts ?? []
  const vehicle = vehicles.find((item) => item.tr_id === selectedTrId)
  const alert = alerts.find((item) => item.tr_id === selectedTrId && item.status === 'active')
  const demoTrack = useMemo(() => replayTrack(selectedTrId, demoSnapshot, 'demo'), [selectedTrId, demoSnapshot])
  const track = source === 'demo' ? demoTrack : liveTrack

  useEffect(() => {
    if (source !== 'demo' || !playing || scenario === 'disconnected') return
    const timer = window.setInterval(() => {
      setElapsedSeconds((current) => current >= REPLAY_DURATION_S ? 0 : current + 5)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [source, playing, scenario])

  useEffect(() => {
    if (source !== 'live') return
    return connectLive(
      (message) => setLiveSnapshot((current) => mergeWsMessage(current ?? emptyLiveSnapshot, message)),
      setLiveConnection,
    )
  }, [source])

  useEffect(() => {
    if (source !== 'live' || selectedTrId != null) return
    const next = liveSnapshot?.alerts?.[0]?.tr_id ?? liveSnapshot?.vehicles?.[0]?.tr_id
    if (next != null) setSelectedTrId(next)
  }, [source, selectedTrId, liveSnapshot])

  useEffect(() => {
    if (source !== 'live' || selectedTrId == null) return
    const controller = new AbortController()
    setLiveTrack(null)
    setTrackError(false)
    fetchTrack(selectedTrId, controller.signal)
      .then(setLiveTrack)
      .catch((error: unknown) => { if (!(error instanceof DOMException && error.name === 'AbortError')) setTrackError(true) })
    return () => controller.abort()
  }, [source, selectedTrId])

  function changeScenario(next: Scenario) {
    setScenario(next)
    setElapsedSeconds(0)
    setSelectedTrId(next === 'empty' ? null : 131672)
    setPlaying(next !== 'disconnected')
  }

  function changeSource(next: 'demo' | 'live') {
    setSource(next)
    setSelectedTrId(next === 'demo' ? (scenario === 'empty' ? null : 131672) : null)
  }

  return (
    <div className="dashboard">
      <StatusBar
        snapshot={snapshot} connected={connected} source={source} scenario={scenario}
        playing={playing} onScenarioChange={changeScenario} onTogglePlayback={() => setPlaying((value) => !value)}
        onRestart={() => { setElapsedSeconds(0); setPlaying(scenario !== 'disconnected') }} onSourceChange={changeSource}
      />
      {!connected && <div className="connection-banner"><SignalZero size={17} /> {source === 'live'
        ? liveConnection === 'connecting' ? 'Подключение к живому потоку…' : 'Живой поток недоступен. Повторное подключение выполняется автоматически.'
        : 'Демо-поток прерван. На экране последний снимок; положение бортов может быть устаревшим.'}</div>}
      {source === 'live' && trackError && <div className="route-banner">Маршрут выбранного борта недоступен. Положение и прогноз из потока продолжают отображаться.</div>}
      <div className="workbench">
        <AlertList alerts={alerts} vehicles={vehicles} selectedTrId={selectedTrId} simTime={snapshot.sim_time} onSelect={setSelectedTrId} />
        <VehicleMap source={source} vehicles={vehicles} selectedTrId={selectedTrId} track={track} onSelect={setSelectedTrId} />
        <IncidentCard source={source} connected={connected} vehicle={vehicle} alert={alert} simTime={snapshot.sim_time} />
      </div>
      <MareyChart source={source} track={track} vehicle={vehicle} simTime={snapshot.sim_time} />
      <footer className="dashboard-footer"><span>ПроАкт.Транспорт · {source === 'demo' ? 'демонстрационная версия' : 'живой поток'}</span><span>{source === 'demo' ? 'Синтетический маршрут · прогноз из контрактного примера' : 'Данные backend через WebSocket и REST'}</span></footer>
    </div>
  )
}
