import { useEffect, useMemo, useRef, useState } from 'react'
import { CloudOff, SignalZero } from 'lucide-react'
import AlertList from './components/AlertList'
import IncidentCard, { type ActionOutcome } from './components/IncidentCard'
import MareyChart from './components/MareyChart'
import StatusBar from './components/StatusBar'
import VehicleMap from './components/VehicleMap'
import { connectLive, emptyLiveSnapshot, fetchHorizon, fetchTrack, mergeWsMessage, postAction, type ConnectionState } from './data/liveTransport'
import { replaySnapshot, replayTrack, REPLAY_DURATION_S } from './data/replay'
import type { Scenario } from './data/scenarios'
import type { Alert, HorizonMetrics, TrackResponse, WsMessage } from './types/contracts'
import { stopLabel } from './utils/format'
import { contractTimeMs } from './utils/time'

type Source = 'demo' | 'live'

const TRACK_REFRESH_MS = 15_000
const NETWORK_REFRESH_MS = 60_000
const HORIZON_REFRESH_MS = 10_000
const NETWORK_MAX_VEHICLES = 60

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
  const [selectedTrId, setSelectedTrId] = useState<number | null>(() => initialSource() === 'demo' ? 131672 : null)
  const [playing, setPlaying] = useState(true)
  const [liveSnapshot, setLiveSnapshot] = useState<WsMessage | null>(null)
  const [liveConnection, setLiveConnection] = useState<ConnectionState>('disconnected')
  const [liveTrack, setLiveTrack] = useState<TrackResponse | null>(null)
  const [trackError, setTrackError] = useState(false)
  const [networkTracks, setNetworkTracks] = useState<Record<number, TrackResponse>>({})
  const [horizon, setHorizon] = useState<HorizonMetrics | null>(null)
  const [outcomes, setOutcomes] = useState<Record<number, ActionOutcome>>({})

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
  // Только трек выбранного борта: пока грузится новый, старый не попадает ни на карту, ни в диаграмму.
  const track = source === 'demo' ? demoTrack : (liveTrack?.tr_id === selectedTrId ? liveTrack : null)
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
    if (source !== 'demo' || !playing || scenario === 'disconnected') return
    const timer = window.setInterval(() => {
      setElapsedSeconds((current) => current >= REPLAY_DURATION_S ? 0 : current + 5)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [source, playing, scenario])

  // Перемотка replay (в том числе по кругу --loop): алерты backend сброшены — сбрасываем и исходы решений.
  const lastSimMsRef = useRef<number>(Number.NaN)
  const liveSimTime = liveSnapshot?.sim_time
  useEffect(() => {
    if (!liveSimTime) return
    const now = contractTimeMs(liveSimTime)
    if (now < lastSimMsRef.current - 60_000) setOutcomes({})
    lastSimMsRef.current = now
  }, [liveSimTime])

  useEffect(() => {
    if (source !== 'live') return
    return connectLive(
      (message) => setLiveSnapshot((current) => mergeWsMessage(current ?? emptyLiveSnapshot, message)),
      setLiveConnection,
    )
  }, [source])

  useEffect(() => {
    if (source !== 'live' || selectedTrId != null) return
    const next = liveSnapshot?.alerts?.[0]?.tr_id ?? liveSnapshot?.vehicles?.find((item) => item.forecast)?.tr_id ?? liveSnapshot?.vehicles?.[0]?.tr_id
    if (next != null) setSelectedTrId(next)
  }, [source, selectedTrId, liveSnapshot])

  // Трек выбранного борта: загрузка при выборе и обновление, чтобы след и «Наблюдение» двигались за потоком.
  useEffect(() => {
    if (source !== 'live' || selectedTrId == null) return
    const controller = new AbortController()
    const load = () => fetchTrack(selectedTrId, controller.signal)
      .then((value) => { setLiveTrack(value); setTrackError(false) })
      .catch((error: unknown) => { if (!isAbort(error)) setTrackError(true) })
    setLiveTrack(null)
    setTrackError(false)
    void load()
    const timer = window.setInterval(() => { void load() }, TRACK_REFRESH_MS)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [source, selectedTrId])

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
      const entries = await Promise.all(ids.map((id) =>
        fetchTrack(id, controller.signal).then((value) => [id, value] as const).catch(() => null)))
      if (!controller.signal.aborted) {
        setNetworkTracks(Object.fromEntries(entries.filter((item): item is readonly [number, TrackResponse] => item != null)))
      }
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
      const message = error instanceof Error ? error.message : 'ошибка сети'
      setOutcomes((current) => ({ ...current, [target.tr_id]: { alert_id: target.alert_id, error: message } }))
    }
  }

  function changeScenario(next: Scenario) {
    setScenario(next)
    setOutcomes({})
    setElapsedSeconds(0)
    setSelectedTrId(next === 'empty' ? null : 131672)
    setPlaying(next !== 'disconnected')
  }

  function changeSource(next: Source) {
    setSource(next)
    setOutcomes({})
    setSelectedTrId(next === 'demo' ? (scenario === 'empty' ? null : 131672) : null)
  }

  return (
    <div className="dashboard">
      <StatusBar
        snapshot={snapshot} connected={connected} source={source} scenario={scenario} horizon={horizon}
        playing={playing} onScenarioChange={changeScenario} onTogglePlayback={() => setPlaying((value) => !value)}
        onRestart={() => { setElapsedSeconds(0); setPlaying(scenario !== 'disconnected') }} onSourceChange={changeSource}
      />
      {!connected && <div className="connection-banner"><SignalZero size={17} /> {source === 'live'
        ? liveConnection === 'connecting' ? 'Подключение к живому потоку…' : 'Живой поток недоступен. Повторное подключение выполняется автоматически.'
        : 'Демо-поток прерван. На экране последний снимок; положение бортов может быть устаревшим.'}</div>}
      {degraded && <div className="degraded-banner"><SignalZero size={17} /> Поток телеметрии прерван (режим DEGRADED): пакетов нет дольше 15 с, прогнозы строятся по расписанию. Связь восстановится автоматически.</div>}
      {mlDown && <div className="degraded-banner"><CloudOff size={17} /> ML-ядро недоступно: прогнозы «по расписанию» до восстановления сервиса.</div>}
      {source === 'live' && trackError && <div className="route-banner">Маршрут выбранного борта недоступен. Положение и прогноз из потока продолжают отображаться.</div>}
      <div className="workbench">
        <AlertList alerts={alerts} vehicles={vehicles} selectedTrId={selectedTrId} simTime={snapshot.sim_time} onSelect={setSelectedTrId} />
        <VehicleMap source={source} vehicles={vehicles} selectedTrId={selectedTrId} track={track} onSelect={setSelectedTrId}
          networkTracks={source === 'live' ? networkTracks : undefined} simTime={snapshot.sim_time} />
        <IncidentCard source={source} connected={connected} vehicle={vehicle} alert={alert} simTime={snapshot.sim_time}
          segmentFrom={segmentFrom} outcome={outcome} onAction={handleAction} hasSchedule={hasSchedule} />
      </div>
      <MareyChart source={source} track={track} vehicle={vehicle} simTime={snapshot.sim_time} />
      <footer className="dashboard-footer"><span>ПроАкт.Транспорт · {source === 'demo' ? 'демонстрационная версия' : 'живой поток'}</span><span>{source === 'demo' ? 'Синтетический маршрут · прогноз из контрактного примера' : 'Данные backend через WebSocket и REST'}</span></footer>
    </div>
  )
}
