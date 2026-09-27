import type { HTMLAttributes, ReactNode } from 'react'
import { cx } from './cx'

interface PanelProps extends HTMLAttributes<HTMLElement> {
  as?: 'section' | 'aside' | 'div'
  /** inset — a nested block inside a panel. */
  variant?: 'default' | 'inset'
  /** Content is loading: sets aria-busy. */
  busy?: boolean
}

export function Panel({ as: Tag = 'section', variant = 'default', busy = false, className, ...rest }: PanelProps) {
  return <Tag className={cx('ui-panel', variant === 'inset' && 'ui-panel--inset', className)} aria-busy={busy || undefined} {...rest} />
}

interface PanelHeaderProps {
  title: ReactNode
  titleAs?: 'h2' | 'h3' | 'strong'
  eyebrow?: ReactNode
  /** Leading icon, next to the title. */
  icon?: ReactNode
  /** Trailing content: a counter, an icon, a legend. */
  actions?: ReactNode
  /** Title, icon and description on one line. */
  compact?: boolean
  className?: string
  children?: ReactNode
}

export function PanelHeader({ title, titleAs: Title = 'h2', eyebrow, icon, actions, compact = false, className, children }: PanelHeaderProps) {
  return (
    <div className={cx('ui-panel-header', compact && 'ui-panel-header--compact', className)}>
      <div className="ui-panel-header-text">
        {icon}
        {eyebrow && <span className="ui-eyebrow">{eyebrow}</span>}
        <Title className="ui-panel-title">{title}</Title>
        {children}
      </div>
      {actions}
    </div>
  )
}
