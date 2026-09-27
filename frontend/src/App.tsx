import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, CloudOff, SignalZero, TriangleAlert } from 'lucide-react'
import AlertList from './components/AlertList'
import IncidentCard from './components/IncidentCard'
import MareyChart from './components/MareyChart'
import StatusBar from './components/StatusBar'
import { emptyLiveSnapshot } from './data/liveTransport'
import { replaySnapshot, replayTrack, REPLAY_DURATION_S } from './data/replay'
import { scenarioSnapshot, type Scenario } from './data/scenarios'
import { useDispatcherActions } from './data/useDispatcherActions'
import { useHorizon } from './data/useHorizon'
import { useLiveStream } from './data/useLiveStream'
import { useRouteNetwork } from './data/useRouteNetwork'
import { useSelectedTrack } from './data/useSelectedTrack'
import { stopLabel } from './utils/format'
import { trackAtTime } from './utils/track'
import { Banner, Button } from './ui'
import { contractTimeMs, displayClock } from './utils/time'
import { emptySelection, forecastForSelection, nextAutoSelection, pickVehicle, selectedAlert, selectionAfterEpoch, type Selection } from './utils/selection'

const VehicleMap = lazy(() => import('./components/VehicleMap'))
const defaultDemoAlert = scenarioSnapshot('normal').alerts?.filter((item) => item.status === 'active').sort((a, b) => b.priority - a.priority)[0]
const defaultDemoTrId = defaultDemoAlert?.tr_id ?? 131672

type Source = 'demo' | 'live'

/** По умолчанию — живой поток backend; синтетическое демо — `?source=demo` или переключатель «Источник». */
function initialSource(): Source {
  return new URLSearchParams(window.location.search).get('source') === 'demo' ? 'demo' : 'live'
}

function demoSelection(scenario: Scenario): Selection {
  return scenario === 'empty' ? emptySelection : { trId: defaultDemoTrId, alertId: defaultDemoAlert?.alert_id ?? null, pickedByUser: false }
}

export default function App() {
  const [source, setSource] = useState<Source>(initialSource)
  const [scenario, setScenario] = useState<Scenario>('normal')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [selection, setSelection] = useState<Selection>(() => initialSource() === 'demo' ? demoSelection('normal') : emptySelection)
  const [focusSelectionToken, setFocusSelectionToken] = useState(0)
  const [resetMapViewToken, setResetMapViewToken] = useState(0)
  const [playing, setPlaying] = useState(true)
  const isLive = source === 'live'
  const live = useLiveStream(isLive)
  const liveSnapshot = isLive ? live.snapshot : null
  const liveEpoch = live.state.epoch
  const selectedTrId = selection.trId
  const actions = useDispatcherActions(source)
  const liveTrack = useSelectedTrack(isLive, selectedTrId, liveEpoch)
  const networkTracks = useRouteNetwork(isLive, liveSnapshot?.vehicles)
  const horizon = useHorizon(isLive)

  const demoSnapshot = useMemo(() => replaySnapshot(scenario, elapsedSeconds), [scenario, elapsedSeconds])
  const snapshot = source === 'demo' ? demoSnapshot : liveSnapshot ?? emptyLiveSnapshot
  const liveTimeLagS = isLive ? live.lagS : 0
  const liveWallAgeS = isLive ? live.wallAgeS : 0
  const liveStalled = isLive && live.stalled
  const connected = source === 'demo' ? scenario !== 'disconnected' : live.connected
  const waitingTooLong = isLive && live.waitingTooLong
  const liveConnection = isLive ? live.connection : 'disconnected'
  const hasVehicleSnapshot = source === 'demo' || live.state.hasVehicleSnapshot
  const hasAlertSnapshot = source === 'demo' || live.state.hasAlertSnapshot
  const vehicles = useMemo(() => isLive && !connected
    ? (snapshot.vehicles ?? []).map((item) => ({ ...item, stale: true }))
    : snapshot.vehicles ?? [], [isLive, connected, snapshot.vehicles])
  const alerts = useMemo(() => snapshot.alerts ?? [], [snapshot.alerts])
  const vehicle = vehicles.find((item) => item.tr_id === selectedTrId)
  const alert = selectedAlert(alerts, selectedTrId, selection.alertId)
  const displayForecast = forecastForSelection(vehicle, alert)
  const demoTrack = useMemo(() => replayTrack(selectedTrId, demoSnapshot, 'demo'), [selectedTrId, demoSnapshot])
  const track = useMemo(() => trackAtTime(source === 'demo' ? demoTrack : liveTrack.track, snapshot.sim_time),
    [source, demoTrack, liveTrack.track, snapshot.sim_time])
  // /tracks у борта без расписания (юнит эмулятора) отдаёт пустой список остановок
  const hasSchedule = isLive && track ? track.stops.length > 0 : undefined
  // Исход решения показываем только для того алерта, по которому оно принято.
  const storedOutcome = selectedTrId != null ? actions.outcomes[selectedTrId] : undefined
  const outcome = storedOutcome && (!alert || storedOutcome.alert_id === alert.alert_id) ? storedOutcome : undefined
  const liveMode = isLive && connected ? snapshot.status?.mode : undefined
  const degraded = liveMode === 'DEGRADED'
  // ml-core «упал» только если прогнозы уже считаются запасным правилом (до первого прогноза model_version = 'none')
  const mlDown = isLive && connected && snapshot.status?.ml_core_ok === false &&
    (snapshot.status?.model_version ?? 'none') !== 'none'
  const trackError = isLive && liveTrack.error

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

  // «Связь восстановлена» — только после настоящего обрыва или застоя живого потока, не при первом подключении.
  const [restoredAt, setRestoredAt] = useState<string | null>(null)
  const linkLost = useRef(false)
  const everConnected = useRef(false)
  useEffect(() => {
    if (!isLive) { linkLost.current = false; everConnected.current = false; setRestoredAt(null); return }
    if (!connected) { if (everConnected.current) linkLost.current = true; return }
    everConnected.current = true
    if (!linkLost.current) return
    linkLost.current = false
    setRestoredAt(displayClock(snapshot.sim_time))
    const timer = window.setTimeout(() => setRestoredAt(null), 5000)
    return () => window.clearTimeout(timer)
  }, [isLive, connected])

  useEffect(() => {
    if (source !== 'demo' || !playing || scenario === 'disconnected') return
    const timer = window.setInterval(() => {
      setElapsedSeconds((current) => current >= REPLAY_DURATION_S ? 0 : current + 5)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [source, playing, scenario])

  // Новая эпоха потока (переподключение или перемотка replay) заново выбирает предупреждение и сбрасывает вид карты.
  // Перемотка на backend сбрасывает предупреждения, поэтому вместе с ними — и исходы решений; переподключение их сохраняет.
  useLayoutEffect(() => {
    if (!liveEpoch || !live.snapshot) return
    const epochSnapshot = live.snapshot
    setSelection((current) => selectionAfterEpoch(current, epochSnapshot))
    setResetMapViewToken((current) => current + 1)
    if (live.state.epochReason === 'clock-jump') actions.reset()
  }, [liveEpoch])

  useEffect(() => {
    if (nextAutoSelection(selection, alerts, liveSnapshot) === selection) return
    setSelection((current) => nextAutoSelection(current, alerts, liveSnapshot))
  }, [selection, alerts, liveSnapshot])

  function changeScenario(next: Scenario) {
    setScenario(next)
    actions.reset()
    setElapsedSeconds(0)
    setSelection(demoSelection(next))
    setPlaying(next !== 'disconnected')
    setResetMapViewToken((current) => current + 1)
  }

  function changeSource(next: Source) {
    if (next === source) return
    setResetMapViewToken((current) => current + 1)
    setSource(next)
    actions.reset()
    setSelection(next === 'demo' ? demoSelection(scenario) : emptySelection)
  }

  function selectVehicle(trId: number) {
    setSelection(pickVehicle(alerts, trId))
    setFocusSelectionToken((current) => current + 1)
  }

  return (
    <div className="dashboard">
      <a className="skip-link" href="#alerts-feed">К предупреждениям</a>
      <h1 className="sr-only">ПроАкт.Транспорт — диспетчерская</h1>
      <StatusBar
        snapshot={snapshot} connected={connected} source={source} scenario={scenario} horizon={horizon}
        liveConnection={liveConnection} liveStalled={liveStalled} hasVehicleSnapshot={hasVehicleSnapshot} hasAlertSnapshot={hasAlertSnapshot}
        lastVehicleFrameAt={live.state.lastVehicleFrameAt} wallNow={live.state.now} liveTimeLagS={liveTimeLagS}
        droppedFrames={live.droppedFrames} lastDropReason={live.lastDropReason}
        playing={playing} onScenarioChange={changeScenario} onTogglePlayback={() => setPlaying((value) => !value)}
        onRestart={() => { setElapsedSeconds(0); setPlaying(scenario !== 'disconnected') }} onSourceChange={changeSource}
      />
      <div className="dashboard-banners">
      {!connected && <Banner tone="error" className="connection-banner" icon={<SignalZero size={17} />}
        action={waitingTooLong && <Button onClick={() => changeSource('demo')}>Вернуться в демо</Button>}>{source === 'live'
        ? liveConnection === 'connected' ? waitingTooLong ? 'Данные о бортах не поступают. Проверьте источник или вернитесь в демо.'
          : liveStalled ? 'Данные о бортах не обновляются более 15 секунд. Показан последний снимок.' : 'Соединение установлено. Ожидаем новый снимок с положением бортов.'
          : liveConnection === 'connecting' ? 'Подключение к живому потоку…' : 'Живой поток недоступен. Повторное подключение выполняется автоматически.'
        : 'Демо-поток прерван. На экране последний снимок; положение бортов может быть устаревшим.'}</Banner>}
      {connected && restoredAt && <Banner tone="success" className="restored-banner" icon={<CheckCircle2 size={17} />}>Связь восстановлена в {restoredAt}</Banner>}
      {degraded && <Banner tone="warning" className="degraded-banner" icon={<TriangleAlert size={17} />}>Поток телеметрии прерван (деградация): пакетов нет дольше 15 с, прогнозы строятся по расписанию. Связь восстановится автоматически.</Banner>}
      {mlDown && <Banner tone="warning" className="degraded-banner" icon={<CloudOff size={17} />}>ML-ядро недоступно: прогнозы «по расписанию» до восстановления сервиса.</Banner>}
      {source === 'live' && trackError && <Banner tone="warning" className="route-banner">Маршрут выбранного борта недоступен. Положение и прогноз из потока продолжают отображаться.</Banner>}
      </div>
      <main className="dashboard-main">
      <div className="workbench">
        <AlertList alerts={alerts} vehicles={vehicles} selectedTrId={selectedTrId} selectedAlertId={alert?.alert_id ?? null} simTime={snapshot.sim_time} loading={!hasAlertSnapshot} feed={!connected ? 'paused' : degraded ? 'degraded' : 'live'} onSelect={(trId, alertId) => { setSelection({ trId, alertId, pickedByUser: true }); setFocusSelectionToken((current) => current + 1) }} />
        <Suspense fallback={<section className="map-panel" aria-label="Карта движения бортов"><div className="map-empty">Загрузка карты…</div></section>}>
          <VehicleMap source={source} vehicles={vehicles} selectedTrId={selectedTrId} selectedRisk={displayForecast?.risk ?? null} focusSelectionToken={focusSelectionToken} resetViewToken={resetMapViewToken} track={track} loading={!hasVehicleSnapshot} onSelect={selectVehicle}
            networkTracks={source === 'live' ? networkTracks : undefined} simTime={snapshot.sim_time} />
        </Suspense>
        <IncidentCard key={selectedTrId ?? 'none'} source={source} connected={connected} vehicle={vehicle} alert={alert} forecast={displayForecast} simTime={snapshot.sim_time} positionAgeS={vehicle ? vehicle.last_seen_s + (source === 'live' ? Math.max(liveWallAgeS, liveTimeLagS) : 0) : null} forecastWallAgeS={isLive ? live.streamAgeS : 0}
          segmentFrom={segmentFrom} outcome={outcome} onAction={actions.act} hasSchedule={hasSchedule} />
      </div>
      <div className="marey-band">
        <MareyChart source={source} track={track} forecast={displayForecast} simTime={snapshot.sim_time} loading={isLive && liveTrack.loading} routeError={source === 'live' && trackError} />
      </div>
      </main>
    </div>
  )
}
