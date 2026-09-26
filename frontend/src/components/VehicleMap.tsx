import { useEffect, useRef, useState } from 'react'
import { Compass, Layers3, MapPin, Navigation2 } from 'lucide-react'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl'
import type { FeatureCollection, LineString, Point } from 'geojson'
import type { TrackResponse, VehicleState } from '../types/contracts'
import { validCoordinate } from '../utils/geo'

interface Props {
  source: 'demo' | 'live'
  vehicles: VehicleState[]
  selectedTrId: number | null
  track: TrackResponse | null
  onSelect: (trId: number) => void
}

const emptyPoints: FeatureCollection<Point> = { type: 'FeatureCollection', features: [] }
const emptyLines: FeatureCollection<LineString> = { type: 'FeatureCollection', features: [] }

const offlineStyle: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#142433' } }],
}

// Vite serves the worker as a real module URL; MapLibre's default blob worker
// is blocked in the embedded browser used for the demo and visual QA.
maplibregl.setWorkerUrl(mapWorkerUrl)

function installLayers(map: MapLibreMap, onSelect: (trId: number) => void) {
  map.addSource('planned-route', { type: 'geojson', data: emptyLines })
  map.addLayer({
    id: 'planned-route-line', type: 'line', source: 'planned-route',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': '#7ec7da', 'line-width': 3, 'line-opacity': 0.75, 'line-dasharray': [2, 1.5] },
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
    paint: { 'circle-color': '#142433', 'circle-radius': 5, 'circle-stroke-color': '#b5e2e8', 'circle-stroke-width': 2 },
  })
  map.addSource('vehicles', { type: 'geojson', data: emptyPoints })
  map.addLayer({
    id: 'vehicles-glow', type: 'circle', source: 'vehicles',
    paint: {
      'circle-color': ['match', ['get', 'risk'], 'red', '#ff5d64', 'yellow', '#f4bd62', 'green', '#59ccab', '#8ca4b1'],
      'circle-radius': ['case', ['get', 'selected'], 19, 15],
      'circle-opacity': 0.18,
    },
  })
  map.addLayer({
    id: 'vehicles-circle', type: 'circle', source: 'vehicles',
    paint: {
      'circle-color': ['match', ['get', 'risk'], 'red', '#ff5d64', 'yellow', '#f4bd62', 'green', '#59ccab', '#8ca4b1'],
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
  map.on('mouseenter', 'vehicles-circle', () => { map.getCanvas().style.cursor = 'pointer' })
  map.on('mouseleave', 'vehicles-circle', () => { map.getCanvas().style.cursor = '' })
}

export default function VehicleMap({ source, vehicles, selectedTrId, track, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const onSelectRef = useRef(onSelect)
  const lastFittedRef = useRef<number | null>(null)
  const [ready, setReady] = useState(false)
  onSelectRef.current = onSelect

  useEffect(() => {
    if (!containerRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: offlineStyle,
      center: [37.55, 55.74],
      zoom: 10.5,
      attributionControl: false,
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    map.on('load', () => {
      installLayers(map, (trId) => onSelectRef.current(trId))
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
        },
      })),
    }
    ;(map.getSource('vehicles') as GeoJSONSource).setData(vehicleData)

    const stops = track?.stops.filter((item) => validCoordinate(item.lon, item.lat)).sort((a, b) => a.seq - b.seq) ?? []
    const routeData: FeatureCollection<LineString> = {
      type: 'FeatureCollection',
      features: stops.length >= 2 ? [{
        type: 'Feature', properties: {},
        geometry: { type: 'LineString', coordinates: stops.map((item) => [item.lon, item.lat]) },
      }] : [],
    }
    const stopData: FeatureCollection<Point> = {
      type: 'FeatureCollection',
      features: stops.map((item) => ({
        type: 'Feature', properties: { stop_id: item.stop_id },
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

    if (selectedTrId !== lastFittedRef.current) {
      lastFittedRef.current = selectedTrId
      const coordinates = stops.length > 0 ? stops.map((item) => [item.lon, item.lat]) : validVehicles.map((item) => [item.lon, item.lat])
      if (coordinates.length > 1) {
        const bounds = new maplibregl.LngLatBounds()
        coordinates.forEach(([lon, lat]) => bounds.extend([lon, lat]))
        map.fitBounds(bounds, { padding: 68, maxZoom: 12.8, duration: 650 })
      } else if (coordinates.length === 1) {
        map.easeTo({ center: coordinates[0] as [number, number], zoom: 12.5, duration: 650 })
      }
    }
  }, [vehicles, selectedTrId, track, ready])

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
          <span className="map-offline-label">Работает без тайлов</span>
        </div>
      </div>
      <div className="map-location-label"><Compass size={15} /> {source === 'demo' ? 'МОСКВА · ДЕМО-ДАННЫЕ' : 'МАРШРУТ · ДАННЫЕ ПОТОКА'}</div>
      <div className="map-legend">
        <span><i className="legend-dot legend-red" />Критично</span>
        <span><i className="legend-dot legend-yellow" />Внимание</span>
        <span><i className="legend-dot legend-green" />В графике</span>
      </div>
      <div className="map-route-hint"><Navigation2 size={15} /> Нажмите на борт, чтобы увидеть маршрут</div>
      {vehicles.length === 0 && <div className="map-empty"><MapPin size={30} /><strong>Нет данных о бортах</strong><span>Положение появится после получения потока.</span></div>}
    </section>
  )
}
