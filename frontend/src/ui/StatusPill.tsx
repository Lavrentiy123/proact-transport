import type { ReactNode } from 'react'
import { cx } from './cx'

export type StatusState = 'live' | 'demo' | 'waiting' | 'stale' | 'degraded' | 'offline'

interface Props {
  state: StatusState
  icon?: ReactNode
  title?: string
  className?: string
  children: ReactNode
}

/** Connection and data freshness state. Only statuses use the pill shape and the mono label. */
export default function StatusPill({ state, icon, title, className, children }: Props) {
  return <span className={cx('ui-status-pill', `ui-status--${state}`, className)} title={title}>{icon}<span>{children}</span></span>
}

/** The same state as a dot next to a text label. */
export function StatusDot({ state, className }: { state: StatusState; className?: string }) {
  return <span className={cx('ui-status-dot', `ui-status--${state}`, className)} aria-hidden="true" />
}
