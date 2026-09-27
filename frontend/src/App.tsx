import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { CloudOff, SignalZero, TriangleAlert } from 'lucide-react'
import AlertList from './components/AlertList'
import IncidentCard, { type ActionOutcome } from './components/IncidentCard'
import MareyChart from './components/MareyChart'
import StatusBar from './components/StatusBar'
import { connectLive, emptyLiveFieldTimes, emptyLiveSnapshot, fetchHorizon, fetchTrack, isRewind, isVehicleSnapshot, mergeLiveFrame, postAction, startLiveEpoch, vehicleLagSeconds, type ConnectionState } from './data/liveTransport'
import { replaySnapshot, replayTrack, REPLAY_DURATION_S } from './data/replay'
import { scenarioSnapshot, type Scenario } from './data/scenarios'
import type { Alert, HorizonMetrics, TrackResponse, WsMessage } from './types/contracts'
import { stopLabel } from './utils/format'
import { trackAtTime } from './utils/track'
import { contractTimeMs, contractTimeUs } from './utils/time'
import { forecastForSelection, selectedAlert, selectionPresent, topActiveAlert } from './utils/selection'

const VehicleMap = lazy(() => import('./components/VehicleMap'))
const defaultDemoAlert = scenarioSnapshot('normal').alerts?.filter((item) => item.status === 'active').sort((a, b) => b.priority - a.priority)[0]
const defaultDemoTrId = defaultDemoAlert?.tr_id ?? 131672

type Source = 'demo' | 'live'

const TRACK_REFRESH_MS = 15_000
const NETWORK_REFRESH_MS = 60_000
const HORIZON_REFRESH_MS = 10_000
const NETWORK_MAX_VEHICLES = 60
const NETWORK_CONCURRENCY = 6

/** По умолчанию — живой поток backend; синтетическое демо — `?source=demo` или переключатель «Источник». */
function initialSource(): Source {
  return new URLSearchParams(window.location.search).get('source') === 'demo' ? 'demo' : 'live'
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export default function App() {
  const [source, setSource] = useState<Source>(initialSource)
  const [scenario, setScenario] = useState<Scenario>('normal')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [selectedTrId, setSelectedTrId] = useState<number | null>(() => initialSource() === 'demo' ? defaultDemoTrId : null)
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(() => initialSource() === 'demo' ? defaultDemoAlert?.alert_id ?? null : null)
  const [focusSelectionToken, setFocusSelectionToken] = useState(0)
  const [resetMapViewToken, setResetMapViewToken] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [liveSnapshot, setLiveSnapshot] = useState<WsMessage | null>(null)
  const [liveConnection, setLiveConnection] = useState<ConnectionState>(() => initialSource() === 'live' ? 'connecting' : 'disconnected')
  const [liveConnectedAt, setLiveConnectedAt] = useState<number | null>(null)
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
  const [networkTracks, setNetworkTracks] = useState<Record<number, TrackResponse>>({})
  const [horizon, setHorizon] = useState<HorizonMetrics | null>(null)
  const [outcomes, setOutcomes] = useState<Record<number, ActionOutcome>>({})

  const demoSnapshot = useMemo(() => replaySnapshot(scenario, elapsedSeconds), [scenario, elapsedSeconds])
  const snapshot = source === 'demo' ? demoSnapshot : liveSnapshot ?? emptyLiveSnapshot
  const liveTimeLagS = source === 'live' ? vehicleLagSeconds(snapshot, liveFieldTimesRef.current) ?? 0 : 0
  const liveWallAgeS = source === 'live' && lastVehicleFrameAt != null ? Math.max(0, (wallNow - lastVehicleFrameAt) / 1000) : 0
  const liveStalled = source === 'live' && (liveTimeLagS > 15 || liveWallAgeS > 15)
  const connected = source === 'demo' ? scenario !== 'disconnected' : liveConnection === 'connected' && livePositionsFresh && !liveStalled
  const waitingTooLong = source === 'live' && liveConnection === 'connected' && !livePositionsFresh &&
    liveConnectedAt != null && wallNow - liveConnectedAt >= 5_000
  const hasVehicleSnapshot = source === 'demo' || hasLiveVehicleSnapshot
  const hasAlertSnapshot = source === 'demo' || hasLiveAlertSnapshot
  const vehicles = useMemo(() => source === 'live' && !connected
    ? (snapshot.vehicles ?? []).map((item) => ({ ...item, stale: true }))
    : snapshot.vehicles ?? [], [source, connected, snapshot.vehicles])
  const alerts = useMemo(() => snapshot.alerts ?? [], [snapshot.alerts])
  const vehicle = vehicles.find((item) => item.tr_id === selectedTrId)
  const alert = selectedAlert(alerts, selectedTrId, selectedAlertId)
  const displayForecast = forecastForSelection(vehicle, alert)
  const demoTrack = useMemo(() => replayTrack(selectedTrId, demoSnapshot, 'demo'), [selectedTrId, demoSnapshot])
  const track = useMemo(() => trackAtTime(source === 'demo' ? demoTrack : liveTrack?.tr_id === selectedTrId ? liveTrack : null, snapshot.sim_time),
    [source, demoTrack, liveTrack, selectedTrId, snapshot.sim_time])
  // /tracks у борта без расписания (юнит эмулятора) отдаёт пустой список остановок
  const hasSchedule = source === 'live' && track ? track.stops.length > 0 : undefined
  // Исход решения показываем только для того алерта, по которому оно принято.
  const storedOutcome = selectedTrId != null ? outcomes[selectedTrId] : undefined
  const outcome = storedOutcome && (!alert || storedOutcome.alert_id === alert.alert_id) ? storedOutcome : undefined
  const liveMode = source === 'live' && connected ? snapshot.status?.mode : undefined
  const degraded = liveMode === 'DEGRADED'
  // ml-core «упал» только если прогнозы уже считаются запасным правилом (до первого прогноза model_version = 'none')
  const mlDown = source === 'live' && connected && snapshot.status?.ml_core_ok === false &&
    (snapshot.status?.model_version ?? 'none') !== 'none'

  // Начало участка: последняя остановка с фактом прибытия (детектор), иначе последняя по плану до «сейчас».
  const segmentFrom = useMemo(() => {
    if (!track || !snapshot.sim_time) return null
    const now = contractTimeMs(snapshot.sim_time)
    const stops = [...track.stops].sort((a, b) => a.seq - b.seq)
    const visited = stops.filter((stop) => stop.time_fact != null && contractTimeMs(stop.time_fact) <= now)
    const passed = visited.length > 0 ? visited : stops.filter((stop) => contractTimeMs(stop.time_plan) <= now)
    const last = passed.at(-1)
    return last ? stopLabel(last.name, last.stop_id) : null
  }, [track, snapshot.sim_time])

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
        const awaitingSession = awaitingVehicleSnapshotRef.current
        if (awaitingSession && !isVehicleSnapshot(message)) {
          // Keep the prior session visible as stale while collecting optional
          // fields from the new connection. They are never merged into it.
          const buffered = mergeLiveFrame(pendingSessionSnapshotRef.current, message, pendingSessionTimesRef.current)
          pendingSessionSnapshotRef.current = buffered.snapshot
          pendingSessionTimesRef.current = buffered.times
          return
        }
        // A rewind on the same connection resets backend alerts, so it starts a
        // new epoch exactly like a reconnect does.
        const newEpoch = awaitingSession || isRewind(message, liveFieldTimesRef.current)
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
          setOutcomes({})
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
        setLiveConnectedAt(state === 'connected' ? Date.now() : null)
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

  // У выбранного борта карточка всегда показывает его активное предупреждение, если оно есть:
  // после переподключения, перемотки или снятия события берём самое срочное из оставшихся.
  useEffect(() => {
    if (selectedTrId == null) return
    if (selectedAlertId != null && alerts.some((item) => item.alert_id === selectedAlertId && item.tr_id === selectedTrId && item.status === 'active')) return
    const next = topActiveAlert(alerts, selectedTrId)?.alert_id ?? null
    if (next !== selectedAlertId) setSelectedAlertId(next)
  }, [alerts, selectedTrId, selectedAlertId])

  // Пока ничего не выбрано, карточка открывает самое срочное предупреждение потока.
  useEffect(() => {
    if (source !== 'live' || selectedTrId != null || !liveSnapshot?.vehicles) return
    const top = (liveSnapshot.alerts ?? []).filter((item) => item.status === 'active')
      .sort((a, b) => b.priority - a.priority || b.created_at.localeCompare(a.created_at))[0]
    const next = top?.tr_id ?? liveSnapshot.vehicles.find((item) => item.forecast)?.tr_id
    if (next == null) return
    setSelectedTrId(next)
    setSelectedAlertId(top?.alert_id ?? null)
  }, [source, selectedTrId, liveSnapshot])

  // Трек выбранного борта: загрузка при выборе и обновление, чтобы след и «Наблюдение» двигались за потоком.
  useEffect(() => {
    if (source !== 'live' || selectedTrId == null) {
      setTrackLoading(false)
      setTrackError(false)
      return
    }
    const requestGeneration = trackRequestGenerationRef.current
    let active = true
    let controller: AbortController | null = null
    const load = (initial: boolean) => {
      controller?.abort()
      const current = new AbortController()
      controller = current
      let timedOut = false
      const timeout = window.setTimeout(() => { timedOut = true; current.abort() }, 8_000)
      const relevant = () => active && requestGeneration === trackRequestGenerationRef.current
      if (initial) {
        setLiveTrack(null)
        setTrackError(false)
        setTrackLoading(true)
      }
      fetchTrack(selectedTrId, current.signal)
        .then((next) => { if (relevant()) { setLiveTrack(next); setTrackError(false) } })
        // A failed refresh keeps the last good route; only a failed first load is reported.
        .catch((error: unknown) => { if (initial && relevant() && (timedOut || !isAbort(error))) setTrackError(true) })
        .finally(() => { window.clearTimeout(timeout); if (initial && relevant()) setTrackLoading(false) })
    }
    load(true)
    const timer = window.setInterval(() => load(false), TRACK_REFRESH_MS)
    return () => { active = false; window.clearInterval(timer); controller?.abort() }
  }, [source, selectedTrId, liveEpoch])

  // Сеть маршрутов: плановые остановки всех бортов (без расписания — пропускаются).
  const vehicleIds = useMemo(
    () => (liveSnapshot?.vehicles ?? []).map((item) => item.tr_id).sort((a, b) => a - b).slice(0, NETWORK_MAX_VEHICLES).join(','),
    [liveSnapshot?.vehicles],
  )
  useEffect(() => {
    if (source !== 'live' || !vehicleIds) { setNetworkTracks({}); return }
    const controller = new AbortController()
    const ids = vehicleIds.split(',').map(Number)
    const load = async () => {
      const loaded: Record<number, TrackResponse> = {}
      for (let index = 0; index < ids.length; index += NETWORK_CONCURRENCY) {
        const batch = await Promise.all(ids.slice(index, index + NETWORK_CONCURRENCY).map((id) =>
          fetchTrack(id, controller.signal).then((value) => [id, value] as const).catch(() => null)))
        if (controller.signal.aborted) return
        for (const entry of batch) if (entry) loaded[entry[0]] = entry[1]
      }
      setNetworkTracks(loaded)
    }
    void load()
    const timer = window.setInterval(() => { void load() }, NETWORK_REFRESH_MS)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [source, vehicleIds])

  // Горизонт 10–15 мин и онлайн-MAE по журналу прогнозов потока.
  useEffect(() => {
    if (source !== 'live') { setHorizon(null); return }
    const controller = new AbortController()
    const load = () => fetchHorizon(controller.signal).then(setHorizon).catch(() => { /* панель просто не обновится */ })
    void load()
    const timer = window.setInterval(() => { void load() }, HORIZON_REFRESH_MS)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [source])

  async function handleAction(target: Alert, action: 'apply' | 'dismiss') {
    if (source === 'demo') {
      const outcome: ActionOutcome = {
        alert_id: target.alert_id,
        status: action === 'apply' ? 'applied' : 'dismissed',
        driver_message: action === 'apply'
          ? `Диспетчер: ${target.recommendation?.text ?? `${target.title}. Сообщите обстановку.`}`
          : 'Алерт отклонён диспетчером',
        driver_reply: action === 'apply' ? 'успеваю' : null,
      }
      setOutcomes((current) => ({ ...current, [target.tr_id]: outcome }))
      return
    }
    try {
      const response = await postAction(target.alert_id, action)
      setOutcomes((current) => ({ ...current, [target.tr_id]: response }))
    } catch (error: unknown) {
      const message = error instanceof DOMException && error.name === 'TimeoutError' ? 'нет ответа 8 секунд'
        : error instanceof Error ? error.message : 'ошибка сети'
      setOutcomes((current) => ({ ...current, [target.tr_id]: { alert_id: target.alert_id, error: message } }))
    }
  }

  function changeScenario(next: Scenario) {
    setScenario(next)
    setOutcomes({})
    setElapsedSeconds(0)
    setSelectedTrId(next === 'empty' ? null : defaultDemoTrId)
    setSelectedAlertId(next === 'empty' ? null : defaultDemoAlert?.alert_id ?? null)
    setPlaying(next !== 'disconnected')
    setResetMapViewToken((current) => current + 1)
  }

  function changeSource(next: Source) {
    if (next === source) return
    liveGenerationRef.current += 1
    awaitingVehicleSnapshotRef.current = false
    pendingSessionSnapshotRef.current = emptyLiveSnapshot
    pendingSessionTimesRef.current = emptyLiveFieldTimes()
    trackRequestGenerationRef.current += 1
    setResetMapViewToken((current) => current + 1)
    setSource(next)
    setOutcomes({})
    setLiveConnectedAt(null)
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
    setSelectedAlertId(topActiveAlert(alerts, trId)?.alert_id ?? null)
    setFocusSelectionToken((current) => current + 1)
  }

  return (
    <div className="dashboard">
      <StatusBar
        snapshot={snapshot} connected={connected} source={source} scenario={scenario} horizon={horizon}
        liveConnection={liveConnection} liveStalled={liveStalled} hasVehicleSnapshot={hasVehicleSnapshot} hasAlertSnapshot={hasAlertSnapshot}
        lastVehicleFrameAt={lastVehicleFrameAt} wallNow={wallNow} liveTimeLagS={liveTimeLagS}
        playing={playing} onScenarioChange={changeScenario} onTogglePlayback={() => setPlaying((value) => !value)}
        onRestart={() => { setElapsedSeconds(0); setPlaying(scenario !== 'disconnected') }} onSourceChange={changeSource}
      />
      {!connected && <div className="connection-banner" role="status"><SignalZero size={17} /><span className="connection-message">{source === 'live'
        ? liveConnection === 'connected' ? waitingTooLong ? 'Данные о бортах не поступают. Проверьте источник или вернитесь в демо.'
          : liveStalled ? 'Данные о бортах не обновляются более 15 секунд. Показан последний снимок.' : 'Соединение установлено. Ожидаем новый снимок с положением бортов.'
          : liveConnection === 'connecting' ? 'Подключение к живому потоку…' : 'Живой поток недоступен. Повторное подключение выполняется автоматически.'
        : 'Демо-поток прерван. На экране последний снимок; положение бортов может быть устаревшим.'}</span>
        {waitingTooLong && <button type="button" className="connection-action" onClick={() => changeSource('demo')}>Вернуться в демо</button>}
      </div>}
      {degraded && <div className="degraded-banner" role="status"><TriangleAlert size={17} /> Поток телеметрии прерван (деградация): пакетов нет дольше 15 с, прогнозы строятся по расписанию. Связь восстановится автоматически.</div>}
      {mlDown && <div className="degraded-banner" role="status"><CloudOff size={17} /> ML-ядро недоступно: прогнозы «по расписанию» до восстановления сервиса.</div>}
      {source === 'live' && trackError && <div className="route-banner" role="status">Маршрут выбранного борта недоступен. Положение и прогноз из потока продолжают отображаться.</div>}
      <div className="workbench">
        <AlertList alerts={alerts} vehicles={vehicles} selectedTrId={selectedTrId} selectedAlertId={alert?.alert_id ?? null} simTime={snapshot.sim_time} loading={!hasAlertSnapshot} connected={connected} onSelect={(trId, alertId) => { setSelectedTrId(trId); setSelectedAlertId(alertId); setFocusSelectionToken((current) => current + 1) }} />
        <Suspense fallback={<section className="map-panel" aria-label="Карта движения бортов"><div className="map-empty">Загрузка карты…</div></section>}>
          <VehicleMap source={source} vehicles={vehicles} selectedTrId={selectedTrId} selectedRisk={displayForecast?.risk ?? null} focusSelectionToken={focusSelectionToken} resetViewToken={resetMapViewToken} track={track} loading={!hasVehicleSnapshot} onSelect={selectVehicle}
            networkTracks={source === 'live' ? networkTracks : undefined} simTime={snapshot.sim_time} />
        </Suspense>
        <IncidentCard source={source} connected={connected} vehicle={vehicle} alert={alert} forecast={displayForecast} simTime={snapshot.sim_time} positionAgeS={vehicle ? vehicle.last_seen_s + (source === 'live' ? Math.max(liveWallAgeS, liveTimeLagS) : 0) : null} forecastWallAgeS={source === 'live' && lastStreamAdvanceAt != null ? Math.max(0, (wallNow - lastStreamAdvanceAt) / 1000) : 0}
          segmentFrom={segmentFrom} outcome={outcome} onAction={handleAction} hasSchedule={hasSchedule} />
      </div>
      <MareyChart source={source} track={track} forecast={displayForecast} simTime={snapshot.sim_time} loading={source === 'live' && trackLoading} routeError={source === 'live' && trackError} />
      <footer className="dashboard-footer"><span>ПроАкт.Транспорт · {source === 'demo' ? 'демонстрационная версия' : 'живой поток'}</span><span>{source === 'demo' ? 'Синтетический маршрут · прогноз из контрактного примера' : 'Источник данных определяется подключённым сервером'}</span></footer>
    </div>
  )
}
