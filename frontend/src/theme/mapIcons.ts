import type { Map as MapLibreMap } from 'maplibre-gl'
import { RISK, type RiskKey, type RiskShape } from './risk'

/** Shapes in a 24×24 box; the legend (SVG) and the map (canvas) draw the same geometry. */
export const SHAPE_PATHS: Record<RiskShape, string> = {
  triangle: 'M12 2 L23 21 L1 21 Z',
  diamond: 'M12 1 L23 12 L12 23 L1 12 Z',
  circle: 'M12 2 A10 10 0 1 1 11.99 2 Z',
  ring: 'M12 2 A10 10 0 1 1 11.99 2 Z M12 7 A5 5 0 1 0 12.01 7 Z',
}

export const riskIconName = (risk: RiskKey) => `risk-${RISK[risk].shape}`

const ICON_PX = 48

function shapeImage(shape: RiskShape): ImageData | null {
  if (typeof document === 'undefined' || typeof Path2D === 'undefined') return null
  const canvas = document.createElement('canvas')
  canvas.width = ICON_PX
  canvas.height = ICON_PX
  const context = canvas.getContext('2d')
  if (!context) return null
  context.scale(ICON_PX / 24, ICON_PX / 24)
  context.fillStyle = '#000'
  context.fill(new Path2D(SHAPE_PATHS[shape]), 'evenodd')
  return context.getImageData(0, 0, ICON_PX, ICON_PX)
}

/** Registers the risk shapes as SDF images, so icon-color paints them. Call after every style.load. */
export function addRiskIcons(map: MapLibreMap): boolean {
  let ready = true
  for (const risk of Object.keys(RISK) as RiskKey[]) {
    const name = riskIconName(risk)
    if (map.hasImage(name)) continue
    const image = shapeImage(RISK[risk].shape)
    if (!image) { ready = false; continue }
    map.addImage(name, image, { sdf: true, pixelRatio: 2 })
  }
  return ready
}
