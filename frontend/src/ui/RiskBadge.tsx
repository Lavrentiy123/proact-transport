import type { ReactNode } from 'react'
import { riskKey, riskMeta } from '../theme/risk'
import { cx } from './cx'

interface RiskMarkProps {
  risk: unknown
  /** icon — tinted square with the risk icon; marker — a legend dot. */
  variant?: 'icon' | 'marker'
  size?: number
  className?: string
}

/** Decorative risk cue; the text next to it carries the meaning. */
export function RiskMark({ risk, variant = 'icon', size = 13, className }: RiskMarkProps) {
  const meta = riskMeta(risk)
  const Icon = meta.icon
  return variant === 'marker'
    ? <span className={cx('ui-risk-marker', `risk-${riskKey(risk)}`, className)} data-shape={meta.shape} aria-hidden="true" />
    : <span className={cx('ui-risk-mark', `risk-${riskKey(risk)}`, className)} aria-hidden="true"><Icon size={size} /></span>
}

interface RiskBadgeProps {
  risk: unknown
  /** badge — inline label; strip — full-width band with a value on the right. */
  variant?: 'badge' | 'strip'
  /** Defaults to the short label for a badge and the long one for a strip. */
  label?: ReactNode
  value?: ReactNode
  valueTitle?: string
  className?: string
}

export function RiskBadge({ risk, variant = 'badge', label, value, valueTitle, className }: RiskBadgeProps) {
  const meta = riskMeta(risk)
  const Icon = meta.icon
  if (variant === 'strip') {
    return (
      <div className={cx('ui-risk-strip', `risk-${riskKey(risk)}`, className)}>
        <Icon size={18} aria-hidden="true" />
        <span>{label ?? meta.long}</span>
        {value != null && <strong title={valueTitle}>{value}</strong>}
      </div>
    )
  }
  return <span className={cx('ui-risk-badge', `risk-${riskKey(risk)}`, className)}><Icon size={14} aria-hidden="true" />{label ?? meta.label}{value != null && <strong title={valueTitle}>{value}</strong>}</span>
}
