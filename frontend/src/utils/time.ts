/** Dataset timestamps are timezone-free Moscow wall times. Use UTC arithmetic
 * on their components so the browser's local timezone cannot change durations. */
export function contractTimeMs(value: string): number {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(value)
  if (!match) return Number.NaN
  const [, y, m, d, h, min, s] = match.map(Number)
  return Date.UTC(y, m - 1, d, h, min, s)
}

export function advanceContractTime(value: string, seconds: number): string {
  return new Date(contractTimeMs(value) + seconds * 1000).toISOString().slice(0, 19)
}

export function secondsUntil(target: string, now: string): number {
  return Math.max(0, Math.round((contractTimeMs(target) - contractTimeMs(now)) / 1000))
}

export function displayClock(value: string | undefined): string {
  return value?.slice(11, 19) || '—'
}

export function displayDay(value: string | undefined): string {
  if (!value || !Number.isFinite(contractTimeMs(value))) return '—'
  return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'long', year: 'numeric', timeZone: 'UTC' })
    .format(new Date(contractTimeMs(value)))
}
