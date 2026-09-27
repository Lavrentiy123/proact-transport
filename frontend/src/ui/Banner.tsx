import type { ReactNode } from 'react'
import { cx } from './cx'

export type BannerTone = 'info' | 'warning' | 'error' | 'success'

interface Props {
  tone: BannerTone
  icon?: ReactNode
  action?: ReactNode
  /** Announce changes to screen readers (role="status"). Off for static notes. */
  live?: boolean
  /** inset — a rounded block inside a panel; otherwise a full-width strip. */
  inset?: boolean
  className?: string
  children: ReactNode
}

export default function Banner({ tone, icon, action, live = true, inset = false, className, children }: Props) {
  return (
    <div className={cx('ui-banner', `ui-banner--${tone}`, inset && 'ui-banner--inset', className)} role={live ? 'status' : undefined}>
      {icon}
      <div className="ui-banner-body">{children}</div>
      {action}
    </div>
  )
}
