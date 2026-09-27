export function formatDelay(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const rounded = Math.round(Math.abs(seconds))
  const sign = seconds > 0 ? '+' : seconds < 0 ? '−' : ''
  return `${sign}${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`
}

export function describeDelay(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return 'Прогноз недоступен'
  if (Math.round(seconds) === 0) return 'По графику'
  return `${seconds < 0 ? 'Опережение' : 'Опоздание'} ${formatDelay(Math.abs(seconds)).replace(/^\+/, '')}`
}

export function formatCountdown(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds))
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`
}
