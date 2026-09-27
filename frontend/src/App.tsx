import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { SignalZero } from 'lucide-react'
import AlertList from './components/AlertList'
import IncidentCard from './components/IncidentCard'
import MareyChart from './components/MareyChart'
import StatusBar from './components/StatusBar'
import { connectLive, emptyLiveFieldTimes, emptyLiveSnapshot, fetchTrack, isVehicleSnapshot, mergeLiveFrame, startLiveEpoch, vehicleLagSeconds, type ConnectionState } from './data/liveTransport'
import { replaySnapshot, replayTrack, REPLAY_DURATION_S } from './data/replay'
import { scenarioSnapshot, type Scenario } from './data/scenarios'
import type { TrackResponse, WsMessage } from './types/contracts'
import { trackAtTime } from './utils/track'
import { contractTimeUs } from './utils/time'
import { forecastForSelection, selectedAlert, selectionPresent } from './utils/selection'

const VehicleMap = lazy(() => import('./components/VehicleMap'))
const defaultDemoAlert = scenarioSnapshot('normal').alerts?.filter((item) => item.status === 'active').sort((a, b) => b.priority - a.priority)[0]
const defaultDemoTrId = defaultDemoAlert?.tr_id ?? 131672

export default function App() {
  const [source, setSource] = useState<'demo' | 'live'>('demo')
  const [scenario, setScenario] = useState<Scenario>('normal')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [selectedTrId, setSelectedTrId] = useState<number | null>(defaultDemoTrId)
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(defaultDemoAlert?.alert_id ?? null)
  const [focusSelectionToken, setFocusSelectionToken] = useState(0)
  const [resetMapViewToken, setResetMapViewToken] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [liveSnapshot, setLiveSnapshot] = useState<WsMessage | null>(null)
  const [liveConnection, setLiveConnection] = useState<ConnectionState>('disconnected')
  const [livePositionsFresh, setLivePositionsFresh] = useState(false)
  const [hasLiveVehicleSnapshot, setHasLiveVehicleSnapshot] = useState(false)
  const [hasLiveAlertSnapshot, setHasLiveAlertSnapshot] = useState(false)
  const [lastVehicleFrameAt, setLastVehicleFrameAt] = useState<number | null>(null)
  const [lastStreamAdvanceAt, setLastStreamAdvanceAt] = useState<number | null>(null)
  const [wallNow, setWallNow] = useState(() => Date.now())
  const liveSnapshotRef = useRef<WsMessage>(emptyLiveSnapshot)
  const liveFieldTimesRef = useRef(emptyLiveFieldTimes())
  const liveGenerationRef = useRef(0)
  const awaitingVehicleSnapshotRef = useRef(false)
  const pendingSessionSnapshotRef = useRef<WsMessage>(emptyLiveSnapshot)
  const pendingSessionTimesRef = useRef(emptyLiveFieldTimes())
  const trackRequestGenerationRef = useRef(0)
  const [liveEpoch, setLiveEpoch] = useState(0)
  const [liveTrack, setLiveTrack] = useState<TrackResponse | null>(null)
  const [trackError, setTrackError] = useState(false)
  const [trackLoading, setTrackLoading] = useState(false)

  const demoSnapshot = useMemo(() => replaySnapshot(scenario, elapsedSeconds), [scenario, elapsedSeconds])
  const snapshot = source === 'demo' ? demoSnapshot : liveSnapshot ?? emptyLiveSnapshot
  const liveTimeLagS = source === 'live' ? vehicleLagSeconds(snapshot, liveFieldTimesRef.current) ?? 0 : 0
  const liveWallAgeS = source === 'live' && lastVehicleFrameAt != null ? Math.max(0, (wallNow - lastVehicleFrameAt) / 1000) : 0
  const liveStalled = source === 'live' && (liveTimeLagS > 15 || liveWallAgeS > 15)
  const connected = source === 'demo' ? scenario !== 'disconnected' : liveConnection === 'connected' && livePositionsFresh && !liveStalled
  const hasVehicleSnapshot = source === 'demo' || hasLiveVehicleSnapshot
  const hasAlertSnapshot = source === 'demo' || hasLiveAlertSnapshot
  const vehicles = useMemo(() => source === 'live' && !connected
    ? (snapshot.vehicles ?? []).map((item) => ({ ...item, stale: true }))
    : snapshot.vehicles ?? [], [source, connected, snapshot.vehicles])
  const alerts = snapshot.alerts ?? []
  const vehicle = vehicles.find((item) => item.tr_id === selectedTrId)
  const alert = selectedAlert(alerts, selectedTrId, selectedAlertId)
  const displayForecast = forecastForSelection(vehicle, alert)
  const demoTrack = useMemo(() => replayTrack(selectedTrId, demoSnapshot, 'demo'), [selectedTrId, demoSnapshot])
  const track = useMemo(() => trackAtTime(source === 'demo' ? demoTrack : liveTrack?.tr_id === selectedTrId ? liveTrack : null, snapshot.sim_time),
    [source, demoTrack, liveTrack, selectedTrId, snapshot.sim_time])

  useEffect(() => {
    if (source !== 'live') return
    const timer = window.setInterval(() => setWallNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [source])

  useEffect(() => {
    if (source !== 'demo' || !playing || scenario === 'disconnected') return
    const timer = window.setInterval(() => {
      setElapsedSeconds((current) => current >= REPLAY_DURATION_S ? 0 : current + 5)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [source, playing, scenario])

  useEffect(() => {
    if (source !== 'live') return
    const generation = liveGenerationRef.current
    return connectLive(
      (message) => {
        if (generation !== liveGenerationRef.current) return
        const newEpoch = awaitingVehicleSnapshotRef.current
        if (newEpoch && !isVehicleSnapshot(message)) {
          // Keep the prior session visible as stale while collecting optional
          // fields from the new connection. They are never merged into it.
          const buffered = mergeLiveFrame(pendingSessionSnapshotRef.current, message, pendingSessionTimesRef.current)
          pendingSessionSnapshotRef.current = buffered.snapshot
          pendingSessionTimesRef.current = buffered.times
          return
        }
        const previousTime = newEpoch ? '' : liveSnapshotRef.current.sim_time
        const result = newEpoch
          ? startLiveEpoch(message, pendingSessionSnapshotRef.current, pendingSessionTimesRef.current)
          : mergeLiveFrame(liveSnapshotRef.current, message, liveFieldTimesRef.current)
        if (newEpoch) {
          awaitingVehicleSnapshotRef.current = false
          pendingSessionSnapshotRef.current = emptyLiveSnapshot
          pendingSessionTimesRef.current = emptyLiveFieldTimes()
          trackRequestGenerationRef.current += 1
          setLiveTrack(null)
          setTrackLoading(false)
          setTrackError(false)
          setLiveEpoch((current) => current + 1)
          setSelectedAlertId(null)
          setHasLiveAlertSnapshot(Number.isFinite(result.times.alerts))
          setSelectedTrId((current) => selectionPresent(result.snapshot, current) ? current : null)
          setResetMapViewToken((current) => current + 1)
        }
        liveSnapshotRef.current = result.snapshot
        liveFieldTimesRef.current = result.times
        setLiveSnapshot(result.snapshot)
        if (!previousTime || contractTimeUs(result.snapshot.sim_time) > contractTimeUs(previousTime)) setLastStreamAdvanceAt(Date.now())
        if (result.acceptedVehicles) {
          setHasLiveVehicleSnapshot(true)
          if (result.advancedVehicles) {
            setLastVehicleFrameAt(Date.now())
            setLivePositionsFresh(true)
          }
        }
        if (result.acceptedAlerts) setHasLiveAlertSnapshot(true)
      },
      (state) => {
        if (generation !== liveGenerationRef.current) return
        setLiveConnection(state)
        setLivePositionsFresh(false)
        if (state === 'connected') {
          awaitingVehicleSnapshotRef.current = true
          pendingSessionSnapshotRef.current = emptyLiveSnapshot
          pendingSessionTimesRef.current = emptyLiveFieldTimes()
        }
      },
    )
  }, [source])

  useEffect(() => {
    if (source !== 'live' || !liveSnapshot || liveSnapshot.vehicles == null || selectedTrId == null) return
    const present = selectionPresent(liveSnapshot, selectedTrId)
    if (present) return
    setSelectedTrId(null)
    setSelectedAlertId(null)
  }, [source, selectedTrId, liveSnapshot])

  useEffect(() => {
    if (source !== 'live' || selectedTrId == null) {
      setTrackLoading(false)
      setTrackError(false)
      return
    }
    const controller = new AbortController()
    const requestGeneration = trackRequestGenerationRef.current
    let active = true
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, 8_000)
    setLiveTrack(null)
    setTrackError(false)
    setTrackLoading(true)
    fetchTrack(selectedTrId, controller.signal)
      .then((next) => { if (active && requestGeneration === trackRequestGenerationRef.current) setLiveTrack(next) })
      .catch((error: unknown) => { if (active && requestGeneration === trackRequestGenerationRef.current && (timedOut || !(error instanceof DOMException && error.name === 'AbortError'))) setTrackError(true) })
      .finally(() => { window.clearTimeout(timeout); if (active && requestGeneration === trackRequestGenerationRef.current) setTrackLoading(false) })
    return () => { active = false; window.clearTimeout(timeout); controller.abort() }
  }, [source, selectedTrId, liveEpoch])

  function changeScenario(next: Scenario) {
    setScenario(next)
    setElapsedSeconds(0)
    setSelectedTrId(next === 'empty' ? null : defaultDemoTrId)
    setSelectedAlertId(next === 'empty' ? null : defaultDemoAlert?.alert_id ?? null)
    setPlaying(next !== 'disconnected')
    setResetMapViewToken((current) => current + 1)
  }

  function changeSource(next: 'demo' | 'live') {
    if (next === source) return
    liveGenerationRef.current += 1
    awaitingVehicleSnapshotRef.current = false
    pendingSessionSnapshotRef.current = emptyLiveSnapshot
    pendingSessionTimesRef.current = emptyLiveFieldTimes()
    trackRequestGenerationRef.current += 1
    setResetMapViewToken((current) => current + 1)
    setSource(next)
    setSelectedTrId(next === 'demo' ? (scenario === 'empty' ? null : defaultDemoTrId) : null)
    setSelectedAlertId(next === 'demo' && scenario !== 'empty' ? defaultDemoAlert?.alert_id ?? null : null)
    if (next === 'live') {
      setLiveSnapshot(null)
      setLiveTrack(null)
      setTrackLoading(false)
      setTrackError(false)
      setLivePositionsFresh(false)
      setHasLiveVehicleSnapshot(false)
      setHasLiveAlertSnapshot(false)
      setLastVehicleFrameAt(null)
      setLastStreamAdvanceAt(null)
      setLiveConnection('connecting')
      liveSnapshotRef.current = emptyLiveSnapshot
      liveFieldTimesRef.current = emptyLiveFieldTimes()
    }
  }

  function selectVehicle(trId: number) {
    setSelectedTrId(trId)
    setSelectedAlertId(null)
    setFocusSelectionToken((current) => current + 1)
  }

  return (
    <div className="dashboard">
      <StatusBar
        snapshot={snapshot} connected={connected} source={source} scenario={scenario}
        liveConnection={liveConnection} liveStalled={liveStalled} hasVehicleSnapshot={hasVehicleSnapshot} hasAlertSnapshot={hasAlertSnapshot}
        lastVehicleFrameAt={lastVehicleFrameAt} wallNow={wallNow} liveTimeLagS={liveTimeLagS}
        playing={playing} onScenarioChange={changeScenario} onTogglePlayback={() => setPlaying((value) => !value)}
        onRestart={() => { setElapsedSeconds(0); setPlaying(scenario !== 'disconnected') }} onSourceChange={changeSource}
      />
      {!connected && <div className="connection-banner" role="status"><SignalZero size={17} /> {source === 'live'
        ? liveConnection === 'connected' ? liveStalled ? 'Данные о бортах не обновляются более 15 секунд. Показан последний снимок.' : 'Соединение установлено. Ожидаем новый снимок с положением бортов.'
          : liveConnection === 'connecting' ? 'Подключение к живому потоку…' : 'Живой поток недоступен. Повторное подключение выполняется автоматически.'
        : 'Демо-поток прерван. На экране последний снимок; положение бортов может быть устаревшим.'}</div>}
      {source === 'live' && trackError && <div className="route-banner">Маршрут выбранного борта недоступен. Положение и прогноз из потока продолжают отображаться.</div>}
      <div className="workbench">
        <AlertList alerts={alerts} vehicles={vehicles} selectedTrId={selectedTrId} selectedAlertId={alert?.alert_id ?? null} simTime={snapshot.sim_time} loading={!hasAlertSnapshot} onSelect={(trId, alertId) => { setSelectedTrId(trId); setSelectedAlertId(alertId); setFocusSelectionToken((current) => current + 1) }} />
        <Suspense fallback={<section className="map-panel" aria-label="Карта движения бортов"><div className="map-empty">Загрузка карты…</div></section>}>
          <VehicleMap source={source} vehicles={vehicles} selectedTrId={selectedTrId} selectedRisk={displayForecast?.risk ?? null} focusSelectionToken={focusSelectionToken} resetViewToken={resetMapViewToken} track={track} loading={!hasVehicleSnapshot} onSelect={selectVehicle} />
        </Suspense>
        <IncidentCard source={source} connected={connected} vehicle={vehicle} alert={alert} forecast={displayForecast} simTime={snapshot.sim_time} positionAgeS={vehicle ? vehicle.last_seen_s + (source === 'live' ? Math.max(liveWallAgeS, liveTimeLagS) : 0) : null} forecastWallAgeS={source === 'live' && lastStreamAdvanceAt != null ? Math.max(0, (wallNow - lastStreamAdvanceAt) / 1000) : 0} />
      </div>
      <MareyChart source={source} track={track} forecast={displayForecast} simTime={snapshot.sim_time} loading={source === 'live' && trackLoading} routeError={source === 'live' && trackError} />
      <footer className="dashboard-footer"><span>ПроАкт.Транспорт · {source === 'demo' ? 'демонстрационная версия' : 'выбранный поток'}</span><span>{source === 'demo' ? 'Синтетический маршрут · прогноз из контрактного примера' : 'Источник данных определяется подключённым сервером'}</span></footer>
    </div>
  )
}
