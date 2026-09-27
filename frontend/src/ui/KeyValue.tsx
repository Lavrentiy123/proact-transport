import type { ReactNode } from 'react'
import { cx } from './cx'

export interface KeyValueRow {
  key?: string
  label: ReactNode
  value: ReactNode
}

interface Props {
  rows: KeyValueRow[]
  /** row — separated rows in a framed box; dense — compact rows without a frame. */
  variant?: 'row' | 'dense'
  /** Values are out of date: they are shown muted. */
  stale?: boolean
  className?: string
  'aria-label'?: string
}

export default function KeyValue({ rows, variant = 'row', stale = false, className, 'aria-label': ariaLabel }: Props) {
  return (
    <div className={cx('ui-kv', `ui-kv--${variant}`, stale && 'is-stale', className)} aria-label={ariaLabel}>
      {rows.map((row, index) => (
        <div className="ui-kv-row" key={row.key ?? index}><span className="ui-kv-label">{row.label}</span><strong className="ui-kv-value">{row.value}</strong></div>
      ))}
    </div>
  )
}
