import { useEffect, useRef, useState } from 'react'
import { Compass, Layers3, MapPin, Navigation2 } from 'lucide-react'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl'
import type { FeatureCollection, LineString, Point } from 'geojson'
import type { TrackResponse, VehicleState } from '../types/contracts'
import { formatDelay, stopLabel } from '../utils/format'
import { validCoordinate } from '../utils/geo'
import { contractTimeMs } from '../utils/time'

interface Props {
  source: 'demo' | 'live'
  vehicles: VehicleState[]
  selectedTrId: number | null
  track: TrackResponse | null
  onSelect: (trId: number) => void
  /** Маршруты всех бортов (живой режим): сеть на карте с цветом риска борта. */
  networkTracks?: Record<number, TrackResponse>
  simTime?: string
}

const emptyPoints: FeatureCollection<Point> = { type: 'FeatureCollection', features: [] }
const emptyLines: FeatureCollection<LineString> = { type: 'FeatureCollection', features: [] }

// Стиль без источников: событие 'load' приходит сразу, слои схемы ставятся не дожидаясь тайлов.
const baseStyle: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#142433' } }],
}
// Подложка OpenStreetMap, приглушённая под тёмную тему, добавляется под слои схемы после 'load'. Без интернета
// или на медленном VPN тайлы не грузятся — маршруты, остановки и борта видны всё равно.
const osmSource: maplibregl.RasterSourceSpecification = {
  type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, maxzoom: 19,
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}
const osmLayer: maplibregl.RasterLayerSpecification = {
  id: 'osm', type: 'raster', source: 'osm',
  paint: { 'raster-opacity': 0.5, 'raster-saturation': -0.7, 'raster-brightness-max': 0.6 },
}
const riskColor: maplibregl.ExpressionSpecification = ['match', ['get', 'risk'], 'red', '#ff5d64', 'yellow', '#f4bd62', 'green', '#59ccab', '#8ca4b1']
const riskNames: Record<string, string> = { red: 'критично', yellow: 'внимание', green: 'в графике', unknown: 'нет прогноза' }
const NETWORK_BACK_MS = 15 * 60_000
const NETWORK_AHEAD_MS = 45 * 60_000

// Vite serves the worker as a real module URL; MapLibre's default blob worker
// is blocked in the embedded browser used for the demo and visual QA.
maplibregl.setWorkerUrl(mapWorkerUrl)

function installLayers(map: MapLibreMap, onSelect: (trId: number) => void) {
  map.addSource('network', { type: 'geojson', data: emptyLines })
  map.addLayer({
    id: 'network-line', type: 'line', source: 'network',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': riskColor, 'line-width': 2.5, 'line-opacity': 0.55 },
  })
  map.addSource('planned-route', { type: 'geojson', data: emptyLines })
  map.addLayer({
    id: 'planned-route-line', type: 'line', source: 'planned-route',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: {
      'line-color': ['match', ['get', 'risk'], 'red', '#ff5d64', 'yellow', '#f4bd62', 'green', '#59ccab', '#7ec7da'],
      'line-width': 4, 'line-opacity': 0.9, 'line-dasharray': [2, 1.5],
    },
  })
  map.addSource('vehicle-trail', { type: 'geojson', data: emptyLines })
  map.addLayer({
    id: 'vehicle-trail-line', type: 'line', source: 'vehicle-trail',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': '#f1bd67', 'line-width': 4, 'line-opacity': 0.92 },
  })
  map.addSource('planned-stops', { type: 'geojson', data: emptyPoints })
  map.addLayer({
    id: 'planned-stops-circle', type: 'circle', source: 'planned-stops',
    paint: {
      'circle-color': ['case', ['get', 'target'], '#ff897f', '#142433'],
      'circle-radius': ['case', ['get', 'target'], 8, 5],
      'circle-stroke-color': ['case', ['get', 'target'], '#ffffff', '#b5e2e8'],
      'circle-stroke-width': 2,
    },
  })
  map.addSource('vehicles', { type: 'geojson', data: emptyPoints })
  map.addLayer({
    id: 'vehicles-glow', type: 'circle', source: 'vehicles',
    paint: {
      'circle-color': riskColor,
      'circle-radius': ['case', ['get', 'selected'], 19, 15],
      'circle-opacity': 0.18,
    },
  })
  map.addLayer({
    id: 'vehicles-circle', type: 'circle', source: 'vehicles',
    paint: {
      'circle-color': riskColor,
      'circle-radius': ['case', ['get', 'selected'], 10, 8],
      'circle-stroke-color': '#f6fbff',
      'circle-stroke-width': ['case', ['get', 'selected'], 3, 2],
      'circle-opacity': ['case', ['get', 'stale'], 0.58, 1],
    },
  })
  map.on('click', 'vehicles-circle', (event) => {
    const trId = Number(event.features?.[0]?.properties?.tr_id)
    if (Number.isFinite(trId)) onSelect(trId)
  })
  const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, className: 'vehicle-popup' })
  map.on('mouseenter', 'vehicles-circle', (event) => {
    map.getCanvas().style.cursor = 'pointer'
    const feature = event.features?.[0]
    if (!feature || feature.geometry.type !== 'Point') return
    const props = feature.properties ?? {}
    const delay = typeof props.delay === 'number' ? formatDelay(props.delay) : '—'
    const target = props.target ? `<br>к ${String(props.target)}` : ''
    popup.setLngLat(feature.geometry.coordinates as [number, number])
      .setHTML(`<strong>Борт ${String(props.tr_id)}</strong><br>прогноз ${delay} · ${riskNames[String(props.risk)] ?? ''}${target}`)
      .addTo(map)
  })
  map.on('mouseleave', 'vehicles-circle', () => { map.getCanvas().style.cursor = ''; popup.remove() })
}

export default function VehicleMap({ source, vehicles, selectedTrId, track, onSelect, networkTracks, simTime }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const onSelectRef = useRef(onSelect)
  const fittedRouteRef = useRef<number | null>(null)
  const centeredVehicleRef = useRef<number | null | undefined>(undefined)
  const [ready, setReady] = useState(false)
  onSelectRef.current = onSelect

  useEffect(() => {
    if (!containerRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: baseStyle,
      center: [37.55, 55.74],
      zoom: 10.5,
      attributionControl: { compact: true },
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    map.on('load', () => {
      installLayers(map, (trId) => onSelectRef.current(trId))
      map.addSource('osm', osmSource)
      map.addLayer(osmLayer, 'network-line')
      setReady(true)
    })
    mapRef.current = map
    return () => {
      setReady(false)
      map.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return

    const validVehicles = vehicles.filter((item) => validCoordinate(item.lon, item.lat))
    const vehicleData: FeatureCollection<Point> = {
      type: 'FeatureCollection',
      features: validVehicles.map((item) => ({
        type: 'Feature', geometry: { type: 'Point', coordinates: [item.lon, item.lat] },
        properties: {
          tr_id: item.tr_id,
          risk: item.forecast?.risk ?? 'unknown',
          stale: item.stale,
          selected: item.tr_id === selectedTrId,
          delay: item.forecast?.delay_pred_s ?? null,
          target: item.forecast ? stopLabel(item.forecast.target_stop_name, item.forecast.target_stop_id) : '',
        },
      })),
    }
    ;(map.getSource('vehicles') as GeoJSONSource).setData(vehicleData)

    const riskOf = new Map(vehicles.map((item) => [item.tr_id, item.forecast?.risk ?? 'unknown']))
    const now = simTime ? contractTimeMs(simTime) : Number.NaN
    const inWindow = (time: string) => !Number.isFinite(now) ||
      (contractTimeMs(time) >= now - NETWORK_BACK_MS && contractTimeMs(time) <= now + NETWORK_AHEAD_MS)
    const networkData: FeatureCollection<LineString> = {
      type: 'FeatureCollection',
      features: Object.values(networkTracks ?? {}).flatMap((item) => {
        const path = item.stops.filter((stop) => validCoordinate(stop.lon, stop.lat) && inWindow(stop.time_plan))
          .sort((a, b) => a.seq - b.seq)
        return path.length >= 2 ? [{
          type: 'Feature' as const, properties: { tr_id: item.tr_id, risk: riskOf.get(item.tr_id) ?? 'unknown' },
          geometry: { type: 'LineString' as const, coordinates: path.map((stop) => [stop.lon, stop.lat]) },
        }] : []
      }),
    }
    ;(map.getSource('network') as GeoJSONSource).setData(networkData)

    const selectedVehicle = vehicles.find((item) => item.tr_id === selectedTrId)
    const targetStopId = selectedVehicle?.forecast?.target_stop_id
    const allStops = track?.stops.filter((item) => validCoordinate(item.lon, item.lat)).sort((a, b) => a.seq - b.seq) ?? []
    const windowStops = source === 'live' ? allStops.filter((item) => inWindow(item.time_plan) || item.stop_id === targetStopId) : allStops
    const stops = windowStops.length >= 2 ? windowStops : allStops
    const routeData: FeatureCollection<LineString> = {
      type: 'FeatureCollection',
      features: stops.length >= 2 ? [{
        type: 'Feature', properties: { risk: selectedVehicle?.forecast?.risk ?? 'unknown' },
        geometry: { type: 'LineString', coordinates: stops.map((item) => [item.lon, item.lat]) },
      }] : [],
    }
    const stopData: FeatureCollection<Point> = {
      type: 'FeatureCollection',
      features: stops.map((item) => ({
        type: 'Feature', properties: { stop_id: item.stop_id, target: item.stop_id === targetStopId },
        geometry: { type: 'Point', coordinates: [item.lon, item.lat] },
      })),
    }
    const trail = track?.trail.filter(([, lat, lon]) => validCoordinate(lon, lat)) ?? []
    const trailData: FeatureCollection<LineString> = {
      type: 'FeatureCollection',
      features: trail.length >= 2 ? [{
        type: 'Feature', properties: {},
        geometry: { type: 'LineString', coordinates: trail.map(([, lat, lon]) => [lon, lat]) },
      }] : [],
    }
    ;(map.getSource('planned-route') as GeoJSONSource).setData(routeData)
    ;(map.getSource('planned-stops') as GeoJSONSource).setData(stopData)
    ;(map.getSource('vehicle-trail') as GeoJSONSource).setData(trailData)

    // Центрирование в два шага: сразу — к выбранному борту (или ко всем бортам), а когда придёт трек именно
    // этого борта — один раз вписать его маршрут. Трек прошлого борта сюда не попадает (App сверяет tr_id).
    const fit = (coordinates: number[][]) => {
      if (coordinates.length > 1) {
        const bounds = new maplibregl.LngLatBounds()
        coordinates.forEach(([lon, lat]) => bounds.extend([lon, lat]))
        map.fitBounds(bounds, { padding: 68, maxZoom: 12.8, duration: 650 })
      } else if (coordinates.length === 1) {
        map.easeTo({ center: coordinates[0] as [number, number], zoom: 12.5, duration: 650 })
      }
    }
    if (selectedTrId != null && track?.tr_id === selectedTrId && stops.length > 0 && fittedRouteRef.current !== selectedTrId) {
      fittedRouteRef.current = selectedTrId
      centeredVehicleRef.current = selectedTrId
      fit(stops.map((item) => [item.lon, item.lat]))
    } else if (centeredVehicleRef.current !== selectedTrId) {
      const vehicleNow = validVehicles.find((item) => item.tr_id === selectedTrId)
      if (selectedTrId == null ? validVehicles.length > 0 : vehicleNow != null) {
        centeredVehicleRef.current = selectedTrId
        if (selectedTrId !== fittedRouteRef.current) fittedRouteRef.current = null
        fit(vehicleNow ? [[vehicleNow.lon, vehicleNow.lat]] : validVehicles.map((item) => [item.lon, item.lat]))
      }
    }
  }, [vehicles, selectedTrId, track, ready, networkTracks, simTime, source])

  return (
    <section className="map-panel" aria-label="Схема движения бортов">
      <div ref={containerRef} className="map-canvas" />
      <div className="map-grid-overlay" aria-hidden="true" />
      <div className="map-topline">
        <span><Layers3 size={15} /> Схема маршрутов</span>
        <div className="map-topline-actions">
          {vehicles.length > 0 && <label className="map-vehicle-picker">Борт
            <select value={selectedTrId ?? ''} onChange={(event) => onSelect(Number(event.target.value))} aria-label="Выбрать борт на карте">
              <option value="" disabled>Выберите</option>
              {vehicles.map((item) => <option key={item.tr_id} value={item.tr_id}>{item.tr_id}</option>)}
            </select>
          </label>}
          <span className="map-offline-label" title="Без интернета подложка не грузится — схема маршрутов и борта остаются">Подложка © OpenStreetMap</span>
        </div>
      </div>
      <div className="map-location-label"><Compass size={15} /> {source === 'demo' ? 'МОСКВА · ДЕМО-ДАННЫЕ' : 'МАРШРУТ · ДАННЫЕ ПОТОКА'}</div>
      <div className="map-legend">
        <span><i className="legend-dot legend-red" />Критично</span>
        <span><i className="legend-dot legend-yellow" />Внимание</span>
        <span><i className="legend-dot legend-green" />В графике</span>
        <span><i className="legend-dot legend-grey" />Нет прогноза</span>
        <span><i className="legend-dot legend-target" />Целевая остановка</span>
      </div>
      <div className="map-route-hint"><Navigation2 size={15} /> Нажмите на борт, чтобы увидеть маршрут</div>
      {vehicles.length === 0 && <div className="map-empty"><MapPin size={30} /><strong>Нет данных о бортах</strong><span>Положение появится после получения потока.</span></div>}
    </section>
  )
}
