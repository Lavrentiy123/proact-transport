import { CircleCheck, CircleDashed, Diamond, TriangleAlert, type LucideIcon } from 'lucide-react'
import type { Risk } from '../types/contracts'

export type RiskKey = Risk | 'none'
/** Secondary cue besides colour (WCAG 1.4.1); markers switch to these shapes in stage 3. */
export type RiskShape = 'triangle' | 'diamond' | 'circle' | 'ring'

export interface RiskMeta {
  label: string
  long: string
  icon: LucideIcon
  shape: RiskShape
  /** CSS custom property name, for MapLibre via cssToken(). */
  token: string
  cssVar: string
  tintVar: string
}

/** The only source of risk labels, icons, shapes and colours. */
export const RISK: Record<RiskKey, RiskMeta> = {
  red: { label: 'Критично', long: 'Критический риск', icon: TriangleAlert, shape: 'triangle', token: '--risk-red', cssVar: 'var(--risk-red)', tintVar: 'var(--risk-red-tint)' },
  yellow: { label: 'Внимание', long: 'Требует внимания', icon: Diamond, shape: 'diamond', token: '--risk-yellow', cssVar: 'var(--risk-yellow)', tintVar: 'var(--risk-yellow-tint)' },
  green: { label: 'В графике', long: 'В графике', icon: CircleCheck, shape: 'circle', token: '--risk-green', cssVar: 'var(--risk-green)', tintVar: 'var(--risk-green-tint)' },
  none: { label: 'Нет прогноза', long: 'Риск не определен', icon: CircleDashed, shape: 'ring', token: '--risk-none', cssVar: 'var(--risk-none)', tintVar: 'var(--risk-none-tint)' },
}

export const RISK_LEVELS = ['red', 'yellow', 'green'] as const satisfies readonly Risk[]

export function riskKey(risk: unknown): RiskKey {
  return risk === 'red' || risk === 'yellow' || risk === 'green' ? risk : 'none'
}

export function riskMeta(risk: unknown): RiskMeta {
  return RISK[riskKey(risk)]
}
