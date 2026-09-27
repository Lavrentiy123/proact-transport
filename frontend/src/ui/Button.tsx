import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { LoaderCircle } from 'lucide-react'
import { cx } from './cx'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'icon'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  icon?: ReactNode
  /** Pending action: shows a spinner in place of the icon and sets aria-busy. Pair it with disabled. */
  loading?: boolean
  block?: boolean
}

export default function Button({ variant = 'secondary', icon, loading = false, block = false, type = 'button', className, children, ...rest }: Props) {
  return (
    <button type={type} className={cx('ui-button', `ui-button--${variant}`, block && 'ui-button--block', className)} aria-busy={loading || undefined} {...rest}>
      {loading ? <LoaderCircle size={14} className="ui-button-spinner" aria-hidden="true" /> : icon}
      {children}
    </button>
  )
}
