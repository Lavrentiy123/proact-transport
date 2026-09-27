import type { ReactNode } from 'react'
import { cx } from './cx'

interface Props {
  icon?: ReactNode
  title: ReactNode
  hint?: ReactNode
  action?: ReactNode
  /** panel — fills a panel; overlay — an opaque card over the map. */
  variant?: 'panel' | 'overlay'
  className?: string
}

export default function EmptyState({ icon, title, hint, action, variant = 'panel', className }: Props) {
  return (
    <div className={cx('ui-empty', `ui-empty--${variant}`, className)}>
      {icon}
      <strong>{title}</strong>
      {hint && <span>{hint}</span>}
      {action}
    </div>
  )
}
