import { useEffect, useRef, useState } from 'react'
import 'maplibre-gl/dist/maplibre-gl.css'
import { Layers3, MapPin } from 'lucide-react'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl'
import type { FeatureCollection, LineString, Point } from 'geojson'
import type { Risk, TrackResponse, VehicleState } from '../types/contracts'
import { formatDelay, stopLabel } from '../utils/format'
import { validCoordinate } from '../utils/geo'
import { contractTimeMs } from '../utils/time'
import { RISK, riskMeta } from '../theme/risk'
import { cssToken } from '../theme/tokens'
import { addRiskIcons, riskIconName, SHAPE_PATHS } from '../theme/mapIcons'
import { Button, EmptyState, PanelHeader } from '../ui'

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
  /** Маршруты всех бортов (живой режим): сеть на карте с цветом риска борта. */
  networkTracks?: Record<number, TrackResponse>
  simTime?: string
}

const emptyPoints: FeatureCollection<Point> = { type: 'FeatureCollection', features: [] }
const emptyLines: FeatureCollection<LineString> = { type: 'FeatureCollection', features: [] }
// Backend returns the whole-day schedule; only the stretch around "now" is drawn.
const NETWORK_BACK_MS = 15 * 60_000
const NETWORK_AHEAD_MS = 45 * 60_000
const basemapStyleUrl = import.meta.env.VITE_MAP_STYLE_URL?.trim() || 'https://tiles.openfreemap.org/styles/dark'
const installedMapHandlers = new WeakSet<MapLibreMap>()

// Built when the map is created, so the colour comes from the loaded tokens.
const offlineStyle = (): maplibregl.StyleSpecification => ({
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': cssToken('--surface-1') } }],
})

// Vite serves the worker as a real module URL; MapLibre's default blob worker
// is blocked in the embedded browser used for the demo and visual QA.
maplibregl.setWorkerUrl(mapWorkerUrl)

function installLayers(map: MapLibreMap, onSelect: (trId: number) => void, onOverlap: (trIds: number[]) => void) {
  const canLabelClusters = Boolean(map.getStyle().glyphs)
  const firstStyleFont = map.getStyle().layers.find((layer) => layer.type === 'symbol' && Array.isArray(layer.layout?.['text-font']))
  const styleFont = firstStyleFont?.type === 'symbol' ? firstStyleFont.layout?.['text-font'] : undefined
  const clusterFont = Array.isArray(styleFont) && styleFont.every((item) => typeof item === 'string') ? styleFont : ['Noto Sans Regular']
  // MapLibre paint cannot read var(--…); tokens are resolved once per style load.
  const riskColor: maplibregl.ExpressionSpecification = ['match', ['get', 'risk'],
    'red', cssToken(RISK.red.token), 'yellow', cssToken(RISK.yellow.token), 'green', cssToken(RISK.green.token), cssToken(RISK.none.token)]
  const surface = cssToken('--surface-1')
  const textPrimary = cssToken('--text-primary')
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
      'line-color': cssToken('--text-tertiary'),
      'line-width': 3, 'line-opacity': 0.95, 'line-dasharray': [2, 1.5],
    },
  })
  map.addSource('vehicle-trail', { type: 'geojson', data: emptyLines })
  map.addLayer({
    id: 'vehicle-trail-line', type: 'line', source: 'vehicle-trail',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': cssToken('--accent'), 'line-width': 5, 'line-opacity': 0.95 },
  })
  map.addSource('planned-stops', { type: 'geojson', data: emptyPoints })
  map.addLayer({
    id: 'planned-stops-circle', type: 'circle', source: 'planned-stops',
    paint: {
      'circle-color': ['case', ['get', 'target'], cssToken('--accent'), surface],
      'circle-radius': ['case', ['get', 'target'], 8, 6],
      'circle-stroke-color': ['case', ['get', 'target'], textPrimary, cssToken('--text-secondary')],
      'circle-stroke-width': 2,
    },
  })
  map.addSource('vehicles', {
    type: 'geojson', data: emptyPoints, cluster: true, clusterMaxZoom: 12, clusterRadius: 44,
    clusterProperties: {
      red_count: ['+', ['case', ['==', ['get', 'risk'], 'red'], 1, 0]],
      yellow_count: ['+', ['case', ['==', ['get', 'risk'], 'yellow'], 1, 0]],
      green_count: ['+', ['case', ['==', ['get', 'risk'], 'green'], 1, 0]],
    },
  })
  // A neutral fill keeps clusters apart from single vehicles; the ring carries the highest risk inside.
  map.addLayer({
    id: 'vehicle-clusters', type: 'circle', source: 'vehicles', filter: ['has', 'point_count'],
    paint: { 'circle-color': cssToken('--surface-2'),
      'circle-radius': ['step', ['get', 'point_count'], 17, 20, 22, 100, 27],
      'circle-stroke-color': ['case', ['>', ['get', 'red_count'], 0], cssToken(RISK.red.token), ['>', ['get', 'yellow_count'], 0], cssToken(RISK.yellow.token),
        ['>', ['get', 'green_count'], 0], cssToken(RISK.green.token), cssToken(RISK.none.token)],
      'circle-stroke-width': 3 },
  })
  if (canLabelClusters) {
    map.addLayer({
      id: 'vehicle-cluster-count', type: 'symbol', source: 'vehicles', filter: ['has', 'point_count'],
      layout: { 'text-field': ['concat', ['get', 'point_count_abbreviated'], ['case', ['>', ['get', 'red_count'], 0], ' !', '']], 'text-size': 12, 'text-font': clusterFont },
      paint: { 'text-color': textPrimary },
    })
  }
  const iconsReady = addRiskIcons(map)
  const iconImage: maplibregl.ExpressionSpecification = ['match', ['get', 'risk'],
    'red', riskIconName('red'), 'yellow', riskIconName('yellow'), 'green', riskIconName('green'), riskIconName('none')]
  // Critical markers are a quarter larger, the selected one larger still.
  const iconSize = (scale: number): maplibregl.ExpressionSpecification =>
    ['*', scale, ['case', ['==', ['get', 'risk'], 'red'], 1.25, 1], ['case', ['to-boolean', ['get', 'selected']], 1.3, 1]]
  const staleOutline = cssToken('--text-tertiary')
  const addMarkerLayers = (id: string, sourceId: string, filter?: maplibregl.FilterSpecification) => {
    const where = filter ? { filter } : {}
    if (!iconsReady) {
      map.addLayer({
        id: `${id}-icon`, type: 'circle', source: sourceId, ...where,
        paint: { 'circle-color': riskColor, 'circle-radius': ['case', ['to-boolean', ['get', 'selected']], 10, 8], 'circle-stroke-color': textPrimary,
          'circle-stroke-width': 2, 'circle-opacity': ['case', ['to-boolean', ['get', 'stale']], 0.55, 1] },
      })
      return
    }
    const layout = { 'icon-allow-overlap': true, 'icon-ignore-placement': true, 'icon-image': iconImage }
    map.addLayer({
      id: `${id}-outline`, type: 'symbol', source: sourceId, ...where,
      layout: { ...layout, 'icon-size': iconSize(1.3) },
      paint: { 'icon-color': ['case', ['to-boolean', ['get', 'stale']], staleOutline, textPrimary], 'icon-opacity': ['case', ['to-boolean', ['get', 'stale']], 0.7, 1] },
    })
    map.addLayer({
      id: `${id}-icon`, type: 'symbol', source: sourceId, ...where,
      layout: { ...layout, 'icon-size': iconSize(1) },
      paint: { 'icon-color': riskColor, 'icon-opacity': ['case', ['to-boolean', ['get', 'stale']], 0.55, 1] },
    })
  }
  addMarkerLayers('vehicles', 'vehicles', ['!', ['has', 'point_count']])
  map.addSource('selected-vehicle', { type: 'geojson', data: emptyPoints })
  // The halo marks only the selected vehicle; under every marker it blurred neighbours together.
  map.addLayer({
    id: 'selected-vehicle-glow', type: 'circle', source: 'selected-vehicle',
    paint: { 'circle-color': riskColor, 'circle-radius': 21, 'circle-opacity': 0.22,
      'circle-stroke-color': ['case', ['to-boolean', ['get', 'stale']], staleOutline, textPrimary], 'circle-stroke-width': 1.5, 'circle-stroke-opacity': 0.8 },
  })
  addMarkerLayers('selected-vehicle', 'selected-vehicle')
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
  const riskText = (risk: unknown) => riskMeta(risk).label.toLowerCase()
  const vehicleTooltip = (properties: Record<string, unknown> | null | undefined) => {
    const delay = typeof properties?.delay === 'number' ? ` · прогноз ${formatDelay(properties.delay)}` : ''
    const target = typeof properties?.target === 'string' && properties.target ? ` к ${properties.target}` : ''
    return `Борт ${properties?.tr_id} · ${riskText(properties?.risk)}${delay}${target}`
  }
  const vehicleWord = (count: number) => count % 10 === 1 && count % 100 !== 11 ? 'борт' : count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14) ? 'борта' : 'бортов'
  map.on('click', 'vehicle-clusters', async (event) => {
    const feature = event.features?.[0]
    const clusterId = Number(feature?.properties?.cluster_id)
    if (!feature || feature.geometry.type !== 'Point' || !Number.isFinite(clusterId)) return
    try {
      const zoom = await (map.getSource('vehicles') as GeoJSONSource).getClusterExpansionZoom(clusterId)
      const duration = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : undefined
      map.easeTo({ center: feature.geometry.coordinates as [number, number], zoom, duration })
    } catch { /* The style may have changed while the expansion was calculated. */ }
  })
  map.on('click', 'vehicles-icon', (event) => {
    const overlaps = [...new Set(map.queryRenderedFeatures(event.point, { layers: ['vehicles-icon'] })
      .map((feature) => Number(feature.properties?.tr_id)).filter(Number.isFinite))]
    if (overlaps.length > 1) {
      onOverlap(overlaps)
      return
    }
    onOverlap([])
    const trId = Number(event.features?.[0]?.properties?.tr_id)
    if (Number.isFinite(trId)) onSelect(trId)
  })
  map.on('mouseenter', 'vehicles-icon', () => { map.getCanvas().style.cursor = 'pointer' })
  map.on('mousemove', 'vehicles-icon', (event) => {
    const feature = event.features?.[0]
    if (feature?.geometry.type !== 'Point') return
    showTooltip(feature.geometry.coordinates as [number, number], vehicleTooltip(feature.properties))
  })
  map.on('mouseleave', 'vehicles-icon', () => { map.getCanvas().style.cursor = ''; hideTooltip() })
  map.on('mouseenter', 'selected-vehicle-icon', () => { map.getCanvas().style.cursor = 'pointer' })
  map.on('mousemove', 'selected-vehicle-icon', (event) => {
    const feature = event.features?.[0]
    if (feature?.geometry.type !== 'Point') return
    showTooltip(feature.geometry.coordinates as [number, number], vehicleTooltip(feature.properties))
  })
  map.on('mouseleave', 'selected-vehicle-icon', () => { map.getCanvas().style.cursor = ''; hideTooltip() })
  map.on('mouseenter', 'vehicle-clusters', () => { map.getCanvas().style.cursor = 'pointer' })
  map.on('mousemove', 'vehicle-clusters', (event) => {
    const feature = event.features?.[0]
    if (feature?.geometry.type !== 'Point') return
    const count = Number(feature.properties?.point_count)
    const red = Number(feature.properties?.red_count)
    const yellow = Number(feature.properties?.yellow_count)
    showTooltip(feature.geometry.coordinates as [number, number], `Группа: ${count} ${vehicleWord(count)} · ${red > 0 ? 'есть критичные' : yellow > 0 ? 'есть предупреждения' : RISK.green.label.toLowerCase()}`)
  })
  map.on('mouseleave', 'vehicle-clusters', () => { map.getCanvas().style.cursor = ''; hideTooltip() })
  map.on('remove', hideTooltip)
}

export default function VehicleMap({ source, vehicles, selectedTrId, selectedRisk, focusSelectionToken, resetViewToken, track, loading, onSelect, networkTracks, simTime }: Props) {
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
        style: basemapStyleUrl === 'offline' ? offlineStyle() : basemapStyleUrl,
        center: [37.55, 55.74],
        zoom: 10.5,
        attributionControl: false,
      })
    } catch {
      setMapUnavailable(true)
      return
    }
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    // Collapsed to the "i" button, so the attribution never covers the legend plate.
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    const collapseAttribution = () => map.getContainer().querySelector('.maplibregl-ctrl-attrib.maplibregl-compact-show')?.classList.remove('maplibregl-compact-show')
    map.once('load', collapseAttribution)
    map.once('idle', collapseAttribution)
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
      map.setStyle(offlineStyle(), { diff: false })
    }
    // A remote style that never arrives (slow VPN, blocked host) must not leave the
    // map without vehicles and routes: the local schematic takes over.
    const styleTimer = offline ? null : setTimeout(() => { if (!styleLoaded) useOfflineStyle() }, 8000)
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
      if (styleTimer) clearTimeout(styleTimer)
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
          delay: item.forecast?.delay_pred_s ?? null,
          target: item.forecast ? stopLabel(item.forecast.target_stop_name, item.forecast.target_stop_id) : '',
        },
      })),
    }
    ;(map.getSource('vehicles') as GeoJSONSource).setData(vehicleData)
    const selectedVehicle = validVehicles.find((item) => item.tr_id === selectedTrId)
    const selectedRiskValue = selectedRisk ?? selectedVehicle?.forecast?.risk ?? 'unknown'
    ;(map.getSource('selected-vehicle') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: selectedVehicle ? [{ type: 'Feature', geometry: { type: 'Point', coordinates: [selectedVehicle.lon, selectedVehicle.lat] },
        properties: { tr_id: selectedVehicle.tr_id, risk: selectedRiskValue, stale: selectedVehicle.stale, selected: true,
          delay: selectedVehicle.forecast?.delay_pred_s ?? null,
          target: selectedVehicle.forecast ? stopLabel(selectedVehicle.forecast.target_stop_name, selectedVehicle.forecast.target_stop_id) : '' } }] : [],
    })

    const now = simTime ? contractTimeMs(simTime) : Number.NaN
    const inWindow = (time: string) => !Number.isFinite(now) ||
      (contractTimeMs(time) >= now - NETWORK_BACK_MS && contractTimeMs(time) <= now + NETWORK_AHEAD_MS)
    const riskOf = new Map(vehicles.map((item) => [item.tr_id, item.forecast?.risk ?? 'unknown']))
    const networkData: FeatureCollection<LineString> = {
      type: 'FeatureCollection',
      features: Object.values(networkTracks ?? {}).flatMap((item) => {
        if (item.tr_id === selectedTrId) return []
        const path = item.stops.filter((stop) => validCoordinate(stop.lon, stop.lat) && inWindow(stop.time_plan))
          .sort((a, b) => a.seq - b.seq)
        return path.length >= 2 ? [{
          type: 'Feature' as const, properties: { tr_id: item.tr_id, risk: riskOf.get(item.tr_id) ?? 'unknown' },
          geometry: { type: 'LineString' as const, coordinates: path.map((stop) => [stop.lon, stop.lat]) },
        }] : []
      }),
    }
    map.getSource<GeoJSONSource>('network')?.setData(networkData)

    const selectedTrack = track?.tr_id === selectedTrId ? track : null
    const targetStopId = selectedVehicle?.forecast?.target_stop_id
    const routeStops = selectedTrack?.stops.filter((item) => validCoordinate(item.lon, item.lat)).sort((a, b) => a.seq - b.seq) ?? []
    // The live track is the whole-day schedule; draw the stretch around "now" and the target stop.
    const windowStops = source === 'live' ? routeStops.filter((item) => inWindow(item.time_plan) || item.stop_id === targetStopId) : routeStops
    const stops = windowStops.length >= 2 ? windowStops : routeStops
    const routeData: FeatureCollection<LineString> = {
      type: 'FeatureCollection',
      features: stops.length >= 2 ? [{
        type: 'Feature', properties: { risk: selectedRiskValue },
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
      // Keyed by the full route, so the live window sliding with time does not refit the view.
      : `${selectedTrId ?? 'all'}:${stops.length > 0 ? `route:${routeStops.map((item) => `${item.lon},${item.lat}`).join(';')}` : selectedVehicle ? 'point' : 'vehicles'}`
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
        // The legend plate sits over the lower left corner; keep the southernmost vehicle above it.
        const narrowMap = map.getContainer().clientWidth <= 640
        map.fitBounds(bounds, {
          padding: { top: 32, bottom: narrowMap ? 130 : 100, left: narrowMap ? 24 : 48, right: narrowMap ? 48 : 64 },
          maxZoom: 12.8,
          duration,
        })
      } else if (coordinates.length === 1) {
        map.easeTo({ center: coordinates[0] as [number, number], zoom: 12.5, duration })
      }
    }
  }, [vehicles, selectedTrId, selectedRisk, track, styleRevision, mapSizeRevision, viewMode, focusSelectionToken, networkTracks, simTime, source])

  return (
    <section id="vehicle-map" className="map-panel" aria-label="Карта движения бортов">
      <PanelHeader compact className="map-header" titleAs="h2" icon={<Layers3 size={16} className="heading-icon" />} title="Карта"
        actions={<div className="map-header-actions">
          {mapUnavailable ? <span className="map-basemap-status">Карта недоступна</span> : basemapStatus === 'offline' && <span className="map-basemap-status" title="Картографические тайлы недоступны, показана схема">Схема без карты</span>}
          {vehicles.length > 0 && <label className="map-vehicle-picker"><span>Борт</span>
            <select value={selectedTrId ?? ''} onChange={(event) => { setOverlappingIds([]); setViewMode('selected'); onSelect(Number(event.target.value)) }} aria-label="Выбрать борт на карте">
              <option value="" disabled>Выберите</option>
              {vehicles.map((item) => <option key={item.tr_id} value={item.tr_id}>{item.tr_id}</option>)}
            </select>
          </label>}
          {vehicles.length > 1 && <Button className="map-overview-button" aria-pressed={viewMode === 'overview'}
            title={viewMode === 'overview' && selectedTrId != null ? 'Вернуться к маршруту выбранного борта' : 'Показать все борта'} onClick={() => {
              userMovedRef.current = false
              if (viewMode === 'overview' && selectedTrId != null) setViewMode('selected')
              else {
                lastFittedRef.current = null
                setViewMode('overview')
                setMapSizeRevision((current) => current + 1)
              }
            }}>{viewMode === 'overview' && selectedTrId != null ? 'К маршруту' : 'Все борта'}</Button>}
        </div>} />
      <div className="map-stage">
      <div ref={containerRef} className="map-canvas" />
      {basemapStatus === 'offline' && <div className="map-grid-overlay" aria-hidden="true" />}
      <div className="map-legend">
        <ul className="map-legend-items" aria-label="Обозначения">
          {(['red', 'yellow', 'green', 'none'] as const).map((risk) => <li key={risk} className={`risk-${risk}`}>
            <svg className="map-legend-shape" viewBox="0 0 24 24" aria-hidden="true"><path d={SHAPE_PATHS[RISK[risk].shape]} fillRule="evenodd" /></svg>{RISK[risk].label}</li>)}
          <li className="map-legend-target"><i className="legend-dot legend-target" />Цель</li>
        </ul>
        <div className="map-count" role="status">{loading ? 'Ожидаем снимок' : `${vehicles.length} в снимке · ${validVehicles.length} ${mapUnavailable ? 'с допустимой позицией' : 'на карте'}`}{hiddenCount > 0 && <span> · {hiddenCount} без допустимой позиции (включая 0,0)</span>}{vehicles.some((item) => item.stale) && <span> · данные устарели</span>}</div>
      </div>
      {overlappingIds.length > 1 && <div className="map-overlap-list" role="group" aria-label="Борта в выбранной точке"><strong>В этой точке несколько бортов</strong><div>{overlappingIds.map((trId) => <Button key={trId} onClick={() => { setOverlappingIds([]); setViewMode('selected'); onSelect(trId) }}>Борт {trId}</Button>)}</div><Button variant="ghost" className="map-overlap-close" onClick={() => setOverlappingIds([])}>Закрыть</Button></div>}
      {mapUnavailable && <div className="map-unavailable"><strong>Карта недоступна в этом браузере</strong><span>Выберите борт из списка. Карточка и предупреждения продолжают работать.</span><div className="map-fallback-list">{vehicles.map((item) => <Button key={item.tr_id} onClick={() => onSelect(item.tr_id)} aria-pressed={selectedTrId === item.tr_id}>Борт {item.tr_id} · {riskMeta(item.forecast?.risk).label.toLowerCase()}</Button>)}</div></div>}
      {vehicles.length === 0 && !mapUnavailable && <EmptyState variant="overlay" className="map-empty" icon={<MapPin size={30} />} title={loading ? 'Ожидаем данные о бортах' : 'Бортов в снимке нет'}
        hint={loading ? 'Положение появится после получения потока.' : 'Текущий снимок содержит пустой список бортов.'} />}
      </div>
    </section>
  )
}
