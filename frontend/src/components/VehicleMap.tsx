import { useEffect, useRef, useState } from 'react'
import 'maplibre-gl/dist/maplibre-gl.css'
import { Compass, Layers3, MapPin, Navigation2 } from 'lucide-react'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl'
import type { FeatureCollection, LineString, Point } from 'geojson'
import type { Risk, TrackResponse, VehicleState } from '../types/contracts'
import { validCoordinate } from '../utils/geo'

interface Props {
  source: 'demo' | 'live'
  vehicles: VehicleState[]
  selectedTrId: number | null
  selectedRisk: Risk | null
  focusSelectionToken: number
  resetViewToken: number
  track: TrackResponse | null
  loading: boolean
  onSelect: (trId: number) => void
}

const emptyPoints: FeatureCollection<Point> = { type: 'FeatureCollection', features: [] }
const emptyLines: FeatureCollection<LineString> = { type: 'FeatureCollection', features: [] }
const basemapStyleUrl = import.meta.env.VITE_MAP_STYLE_URL?.trim() || 'https://tiles.openfreemap.org/styles/dark'
const installedMapHandlers = new WeakSet<MapLibreMap>()

const offlineStyle: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#142433' } }],
}

// Vite serves the worker as a real module URL; MapLibre's default blob worker
// is blocked in the embedded browser used for the demo and visual QA.
maplibregl.setWorkerUrl(mapWorkerUrl)

function installLayers(map: MapLibreMap, onSelect: (trId: number) => void, onOverlap: (trIds: number[]) => void) {
  const canLabelClusters = Boolean(map.getStyle().glyphs)
  const firstStyleFont = map.getStyle().layers.find((layer) => layer.type === 'symbol' && Array.isArray(layer.layout?.['text-font']))
  const styleFont = firstStyleFont?.type === 'symbol' ? firstStyleFont.layout?.['text-font'] : undefined
  const clusterFont = Array.isArray(styleFont) && styleFont.every((item) => typeof item === 'string') ? styleFont : ['Noto Sans Regular']
  map.addSource('planned-route', { type: 'geojson', data: emptyLines })
  map.addLayer({
    id: 'planned-route-line', type: 'line', source: 'planned-route',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': '#7ec7da', 'line-width': 4, 'line-opacity': 0.95, 'line-dasharray': [2, 1.5] },
  })
  map.addSource('vehicle-trail', { type: 'geojson', data: emptyLines })
  map.addLayer({
    id: 'vehicle-trail-line', type: 'line', source: 'vehicle-trail',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': '#f1bd67', 'line-width': 5, 'line-opacity': 0.95 },
  })
  map.addSource('planned-stops', { type: 'geojson', data: emptyPoints })
  map.addLayer({
    id: 'planned-stops-circle', type: 'circle', source: 'planned-stops',
    paint: { 'circle-color': '#142433', 'circle-radius': 6, 'circle-stroke-color': '#b5e2e8', 'circle-stroke-width': 2 },
  })
  map.addSource('vehicles', {
    type: 'geojson', data: emptyPoints, cluster: true, clusterMaxZoom: 12, clusterRadius: 44,
    clusterProperties: {
      red_count: ['+', ['case', ['==', ['get', 'risk'], 'red'], 1, 0]],
      yellow_count: ['+', ['case', ['==', ['get', 'risk'], 'yellow'], 1, 0]],
    },
  })
  map.addLayer({
    id: 'vehicle-clusters', type: 'circle', source: 'vehicles', filter: ['has', 'point_count'],
    paint: { 'circle-color': ['case', ['>', ['get', 'red_count'], 0], '#a94952', ['>', ['get', 'yellow_count'], 0], '#976b36', '#2e6676'],
      'circle-radius': ['step', ['get', 'point_count'], 17, 20, 22, 100, 27], 'circle-stroke-color': '#f2f7f8', 'circle-stroke-width': 1.5 },
  })
  if (canLabelClusters) {
    map.addLayer({
      id: 'vehicle-cluster-count', type: 'symbol', source: 'vehicles', filter: ['has', 'point_count'],
      layout: { 'text-field': ['concat', ['get', 'point_count_abbreviated'], ['case', ['>', ['get', 'red_count'], 0], ' !', '']], 'text-size': 12, 'text-font': clusterFont },
      paint: { 'text-color': '#f5fbfc' },
    })
  }
  map.addLayer({
    id: 'vehicles-glow', type: 'circle', source: 'vehicles', filter: ['!', ['has', 'point_count']],
    paint: {
      'circle-color': ['match', ['get', 'risk'], 'red', '#ff5d64', 'yellow', '#f4bd62', 'green', '#59ccab', '#8ca4b1'],
      'circle-radius': ['case', ['get', 'selected'], 19, 15],
      'circle-opacity': 0.18,
    },
  })
  map.addLayer({
    id: 'vehicles-circle', type: 'circle', source: 'vehicles', filter: ['!', ['has', 'point_count']],
    paint: {
      'circle-color': ['match', ['get', 'risk'], 'red', '#ff5d64', 'yellow', '#f4bd62', 'green', '#59ccab', '#8ca4b1'],
      'circle-radius': ['case', ['get', 'selected'], 10, 8],
      'circle-stroke-color': '#f6fbff',
      'circle-stroke-width': ['case', ['get', 'selected'], 3, 2],
      'circle-opacity': ['case', ['get', 'stale'], 0.58, 1],
    },
  })
  map.addSource('selected-vehicle', { type: 'geojson', data: emptyPoints })
  map.addLayer({
    id: 'selected-vehicle-circle', type: 'circle', source: 'selected-vehicle',
    paint: { 'circle-color': ['match', ['get', 'risk'], 'red', '#ff5d64', 'yellow', '#f4bd62', 'green', '#59ccab', '#8ca4b1'],
      'circle-radius': 11, 'circle-opacity': ['case', ['get', 'stale'], 0.55, 1],
      'circle-stroke-color': ['case', ['get', 'stale'], '#f6c987', '#f6fbff'],
      'circle-stroke-width': ['case', ['get', 'stale'], 4, 3] },
  })
  if (installedMapHandlers.has(map)) return
  installedMapHandlers.add(map)
  let hoverPopup: maplibregl.Popup | null = null
  let hoverKey = ''
  const showTooltip = (coordinates: [number, number], label: string) => {
    const key = `${coordinates.join(',')}:${label}`
    if (hoverKey === key) return
    hoverKey = key
    hoverPopup ??= new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 14, maxWidth: '240px' })
    hoverPopup.setLngLat(coordinates).setText(label).addTo(map)
  }
  const hideTooltip = () => { hoverPopup?.remove(); hoverPopup = null; hoverKey = '' }
  const riskText = (risk: unknown) => risk === 'red' ? 'критично' : risk === 'yellow' ? 'внимание' : risk === 'green' ? 'в графике' : 'без прогноза'
  const vehicleWord = (count: number) => count % 10 === 1 && count % 100 !== 11 ? 'борт' : count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14) ? 'борта' : 'бортов'
  map.on('click', 'vehicle-clusters', async (event) => {
    const feature = event.features?.[0]
    const clusterId = Number(feature?.properties?.cluster_id)
    if (!feature || feature.geometry.type !== 'Point' || !Number.isFinite(clusterId)) return
    try {
      const zoom = await (map.getSource('vehicles') as GeoJSONSource).getClusterExpansionZoom(clusterId)
      map.easeTo({ center: feature.geometry.coordinates as [number, number], zoom })
    } catch { /* The style may have changed while the expansion was calculated. */ }
  })
  map.on('click', 'vehicles-circle', (event) => {
    const overlaps = [...new Set(map.queryRenderedFeatures(event.point, { layers: ['vehicles-circle'] })
      .map((feature) => Number(feature.properties?.tr_id)).filter(Number.isFinite))]
    if (overlaps.length > 1) {
      onOverlap(overlaps)
      return
    }
    onOverlap([])
    const trId = Number(event.features?.[0]?.properties?.tr_id)
    if (Number.isFinite(trId)) onSelect(trId)
  })
  map.on('mouseenter', 'vehicles-circle', () => { map.getCanvas().style.cursor = 'pointer' })
  map.on('mousemove', 'vehicles-circle', (event) => {
    const feature = event.features?.[0]
    if (feature?.geometry.type !== 'Point') return
    showTooltip(feature.geometry.coordinates as [number, number], `Борт ${feature.properties?.tr_id} · ${riskText(feature.properties?.risk)}`)
  })
  map.on('mouseleave', 'vehicles-circle', () => { map.getCanvas().style.cursor = ''; hideTooltip() })
  map.on('mouseenter', 'selected-vehicle-circle', () => { map.getCanvas().style.cursor = 'pointer' })
  map.on('mousemove', 'selected-vehicle-circle', (event) => {
    const feature = event.features?.[0]
    if (feature?.geometry.type !== 'Point') return
    showTooltip(feature.geometry.coordinates as [number, number], `Борт ${feature.properties?.tr_id} · ${riskText(feature.properties?.risk)}`)
  })
  map.on('mouseleave', 'selected-vehicle-circle', () => { map.getCanvas().style.cursor = ''; hideTooltip() })
  map.on('mouseenter', 'vehicle-clusters', () => { map.getCanvas().style.cursor = 'pointer' })
  map.on('mousemove', 'vehicle-clusters', (event) => {
    const feature = event.features?.[0]
    if (feature?.geometry.type !== 'Point') return
    const count = Number(feature.properties?.point_count)
    const red = Number(feature.properties?.red_count)
    const yellow = Number(feature.properties?.yellow_count)
    showTooltip(feature.geometry.coordinates as [number, number], `Группа: ${count} ${vehicleWord(count)} · ${red > 0 ? 'есть критичные' : yellow > 0 ? 'есть предупреждения' : 'в графике'}`)
  })
  map.on('mouseleave', 'vehicle-clusters', () => { map.getCanvas().style.cursor = ''; hideTooltip() })
  map.on('remove', hideTooltip)
}

export default function VehicleMap({ source, vehicles, selectedTrId, selectedRisk, focusSelectionToken, resetViewToken, track, loading, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const onSelectRef = useRef(onSelect)
  const previousFocusRef = useRef(focusSelectionToken)
  const lastFittedRef = useRef<string | null>(null)
  const userMovedRef = useRef(false)
  const [styleRevision, setStyleRevision] = useState(0)
  const [mapSizeRevision, setMapSizeRevision] = useState(0)
  const [basemapStatus, setBasemapStatus] = useState<'loading' | 'online' | 'offline'>(basemapStyleUrl === 'offline' ? 'offline' : 'loading')
  const [mapUnavailable, setMapUnavailable] = useState(false)
  const [viewMode, setViewMode] = useState<'overview' | 'selected'>('overview')
  const [overlappingIds, setOverlappingIds] = useState<number[]>([])
  const validVehicles = vehicles.filter((item) => validCoordinate(item.lon, item.lat))
  const hiddenCount = vehicles.length - validVehicles.length
  onSelectRef.current = onSelect

  useEffect(() => {
    if (focusSelectionToken === previousFocusRef.current) return
    previousFocusRef.current = focusSelectionToken
    userMovedRef.current = false
    lastFittedRef.current = null
    if (selectedTrId != null) setViewMode('selected')
  }, [focusSelectionToken, selectedTrId])

  useEffect(() => {
    setViewMode('overview')
    userMovedRef.current = false
    lastFittedRef.current = null
  }, [source, resetViewToken])

  useEffect(() => {
    if (!containerRef.current) return
    if (import.meta.env.VITE_FORCE_MAP_LIST === '1') {
      setMapUnavailable(true)
      return
    }
    let map: MapLibreMap
    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: basemapStyleUrl === 'offline' ? offlineStyle : basemapStyleUrl,
        center: [37.55, 55.74],
        zoom: 10.5,
      })
    } catch {
      setMapUnavailable(true)
      return
    }
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    const container = map.getContainer()
    const markUserMoved = () => { userMovedRef.current = true }
    const markKeyboardMove = (event: KeyboardEvent) => {
      if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', '+', '-', '=', 'PageUp', 'PageDown'].includes(event.key)) markUserMoved()
    }
    container.addEventListener('pointerdown', markUserMoved)
    container.addEventListener('wheel', markUserMoved, { passive: true })
    container.addEventListener('keydown', markKeyboardMove)
    let lastWidth = container.clientWidth
    let lastHeight = container.clientHeight
    const handleResize = () => {
      const width = container.clientWidth
      const height = container.clientHeight
      if (width === lastWidth && height === lastHeight) return
      lastWidth = width
      lastHeight = height
      map.resize()
      if (!userMovedRef.current) {
        lastFittedRef.current = null
        setMapSizeRevision((current) => current + 1)
      }
    }
    const sizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(handleResize)
    sizeObserver?.observe(container)
    window.addEventListener('resize', handleResize)
    let offline = basemapStyleUrl === 'offline'
    let basemapReady = false
    let styleLoaded = false
    let failedVectorTiles = 0
    let tileCheckTimer: ReturnType<typeof setTimeout> | null = null
    let expectedTileSources = new Set<string>()
    const loadedTileSources = new Set<string>()
    const useOfflineStyle = () => {
      if (offline) return
      offline = true
      if (tileCheckTimer) clearTimeout(tileCheckTimer)
      tileCheckTimer = null
      setBasemapStatus('offline')
      map.setStyle(offlineStyle, { diff: false })
    }
    map.on('style.load', () => {
      styleLoaded = true
      if (!offline) {
        expectedTileSources = new Set(Object.entries(map.getStyle().sources)
          .filter(([, specification]) => specification.type === 'vector' || specification.type === 'raster')
          .map(([sourceId]) => sourceId))
        if (expectedTileSources.size > 0) {
          // MapLibre treats a 404 tile as a settled tile without emitting an
          // error. Require at least one successful base tile before calling
          // the geographic background ready.
          tileCheckTimer = setTimeout(() => {
            if (loadedTileSources.size === 0) useOfflineStyle()
          }, 8000)
        }
      }
      if (map.getSource('vehicles')) return
      installLayers(map, (trId) => {
        setOverlappingIds([])
        setViewMode('selected')
        onSelectRef.current(trId)
      }, setOverlappingIds)
      lastFittedRef.current = null
      setStyleRevision((revision) => revision + 1)
    })
    map.on('sourcedata', (event) => {
      if (offline || !expectedTileSources.has(event.sourceId) || event.tile?.state !== 'loaded') return
      loadedTileSources.add(event.sourceId)
      if (tileCheckTimer) clearTimeout(tileCheckTimer)
      tileCheckTimer = null
    })
    map.on('idle', () => {
      if (!offline && !basemapReady && (expectedTileSources.size === 0 || loadedTileSources.size > 0)) {
        basemapReady = true
        setBasemapStatus('online')
      }
    })
    map.on('error', (event) => {
      // A single glyph, sprite or tile error does not make the map unusable.
      // The local schematic is used when the style fails or several vector
      // tiles fail before the first settled map view.
      if (offline || basemapReady || loadedTileSources.size > 0) return
      if (styleLoaded) {
        const sourceId = (event as unknown as { sourceId?: string }).sourceId
        if (!sourceId || !expectedTileSources.has(sourceId)) return
        failedVectorTiles += 1
        if (failedVectorTiles < 3) return
      }
      useOfflineStyle()
    })
    mapRef.current = map
    return () => {
      if (tileCheckTimer) clearTimeout(tileCheckTimer)
      sizeObserver?.disconnect()
      window.removeEventListener('resize', handleResize)
      container.removeEventListener('pointerdown', markUserMoved)
      container.removeEventListener('wheel', markUserMoved)
      container.removeEventListener('keydown', markKeyboardMove)
      map.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getSource('vehicles') || !map.getSource('selected-vehicle') || !map.getSource('planned-route') || !map.getSource('planned-stops') || !map.getSource('vehicle-trail')) return

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
    const selectedVehicle = validVehicles.find((item) => item.tr_id === selectedTrId)
    ;(map.getSource('selected-vehicle') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: selectedVehicle ? [{ type: 'Feature', geometry: { type: 'Point', coordinates: [selectedVehicle.lon, selectedVehicle.lat] },
        properties: { tr_id: selectedVehicle.tr_id, risk: selectedRisk ?? selectedVehicle.forecast?.risk ?? 'unknown', stale: selectedVehicle.stale } }] : [],
    })

    const selectedTrack = track?.tr_id === selectedTrId ? track : null
    const stops = selectedTrack?.stops.filter((item) => validCoordinate(item.lon, item.lat)).sort((a, b) => a.seq - b.seq) ?? []
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
    const trail = selectedTrack?.trail.filter(([, lat, lon]) => validCoordinate(lon, lat)) ?? []
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

    const fitKey = viewMode === 'overview'
      ? `overview:${validVehicles.map((item) => item.tr_id).sort((a, b) => a - b).join(',')}`
      : `${selectedTrId ?? 'all'}:${stops.length > 0 ? `route:${stops.map((item) => `${item.lon},${item.lat}`).join(';')}` : selectedVehicle ? 'point' : 'vehicles'}`
    if (fitKey !== lastFittedRef.current) {
      lastFittedRef.current = fitKey
      if (userMovedRef.current) return
      map.resize()
      const duration = viewMode === 'overview' || window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 650
      const coordinates = viewMode === 'overview'
        ? validVehicles.map((item) => [item.lon, item.lat])
        : stops.length > 0
          ? stops.map((item) => [item.lon, item.lat])
          : selectedVehicle
            ? [[selectedVehicle.lon, selectedVehicle.lat]]
            : validVehicles.map((item) => [item.lon, item.lat])
      if (coordinates.length > 1) {
        const bounds = new maplibregl.LngLatBounds()
        coordinates.forEach(([lon, lat]) => bounds.extend([lon, lat]))
        // The count, legend and attribution occupy the lower part of the map.
        // Reserve that space when fitting, including on narrow screens where
        // a symmetric padding can place the southernmost vehicle behind them.
        const narrowMap = map.getContainer().clientWidth <= 640
        map.fitBounds(bounds, {
          padding: { top: narrowMap ? 110 : 70, bottom: narrowMap ? 205 : 190, left: narrowMap ? 32 : 68, right: narrowMap ? 32 : 68 },
          maxZoom: 12.8,
          duration,
        })
      } else if (coordinates.length === 1) {
        map.easeTo({ center: coordinates[0] as [number, number], zoom: 12.5, duration })
      }
    }
  }, [vehicles, selectedTrId, selectedRisk, track, styleRevision, mapSizeRevision, viewMode, focusSelectionToken])

  return (
    <section id="vehicle-map" className="map-panel" aria-label="Карта движения бортов">
      <div ref={containerRef} className="map-canvas" />
      {basemapStatus === 'offline' && <div className="map-grid-overlay" aria-hidden="true" />}
      <div className="map-topline">
        <span><Layers3 size={15} /> Карта маршрутов</span>
        <div className="map-topline-actions">
          {vehicles.length > 1 && <button className="map-overview-button" type="button" onClick={() => {
            userMovedRef.current = false
            if (viewMode === 'overview' && selectedTrId != null) setViewMode('selected')
            else {
              lastFittedRef.current = null
              setViewMode('overview')
              setMapSizeRevision((current) => current + 1)
            }
          }}>{viewMode === 'overview' && selectedTrId != null ? 'К маршруту' : 'Все борта'}</button>}
          {vehicles.length > 0 && <label className="map-vehicle-picker">Борт
            <select value={selectedTrId ?? ''} onChange={(event) => { setOverlappingIds([]); setViewMode('selected'); onSelect(Number(event.target.value)) }} aria-label="Выбрать борт на карте">
              <option value="" disabled>Выберите</option>
              {vehicles.map((item) => <option key={item.tr_id} value={item.tr_id}>{item.tr_id}</option>)}
            </select>
          </label>}
          <span className="map-offline-label">{mapUnavailable ? 'Карта недоступна' : basemapStatus === 'online' ? 'Картографическая подложка' : basemapStatus === 'loading' ? 'Загрузка карты…' : 'Схема: тайлы недоступны'}</span>
        </div>
      </div>
      <div className="map-location-label"><Compass size={15} /> {source === 'demo' ? 'МОСКВА · ДЕМО-ДАННЫЕ' : 'МАРШРУТ · ДАННЫЕ ПОТОКА'}</div>
      <div className="map-legend">
        <span><i className="legend-dot legend-red" />Критично</span>
        <span><i className="legend-dot legend-yellow" />Внимание</span>
        <span><i className="legend-dot legend-green" />В графике</span>
        <span className="map-cluster-legend">Группа: цвет по высшему риску</span>
      </div>
      <div className="map-route-hint"><Navigation2 size={15} /> Нажмите на борт, чтобы увидеть маршрут</div>
      <div className="map-count" role="status">{loading ? 'Ожидаем снимок' : `${vehicles.length} в снимке · ${validVehicles.length} ${mapUnavailable ? 'с допустимой позицией' : 'на карте'}`}{hiddenCount > 0 && <span> · {hiddenCount} без допустимой позиции (включая 0,0)</span>}{vehicles.some((item) => item.stale) && <span> · данные устарели</span>}</div>
      {overlappingIds.length > 1 && <div className="map-overlap-list" role="group" aria-label="Борта в выбранной точке"><strong>В этой точке несколько бортов</strong><div>{overlappingIds.map((trId) => <button key={trId} type="button" onClick={() => { setOverlappingIds([]); setViewMode('selected'); onSelect(trId) }}>Борт {trId}</button>)}</div><button className="map-overlap-close" type="button" onClick={() => setOverlappingIds([])}>Закрыть</button></div>}
      {mapUnavailable && <div className="map-unavailable"><strong>Карта недоступна в этом браузере</strong><span>Выберите борт из списка. Карточка и предупреждения продолжают работать.</span><div className="map-fallback-list">{vehicles.map((item) => <button type="button" key={item.tr_id} onClick={() => onSelect(item.tr_id)} aria-pressed={selectedTrId === item.tr_id}>Борт {item.tr_id}{item.forecast ? ` · ${item.forecast.risk === 'red' ? 'критично' : item.forecast.risk === 'yellow' ? 'внимание' : 'в графике'}` : ' · без прогноза'}</button>)}</div></div>}
      {vehicles.length === 0 && !mapUnavailable && <div className="map-empty"><MapPin size={30} /><strong>{loading ? 'Ожидаем данные о бортах' : 'Бортов в снимке нет'}</strong><span>{loading ? 'Положение появится после получения потока.' : 'Текущий снимок содержит пустой список бортов.'}</span></div>}
    </section>
  )
}
