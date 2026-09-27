/** Dataset timestamps are timezone-free Moscow wall times. Use UTC arithmetic
 * on their components so the browser's local timezone cannot change durations. */
export function contractTimeUs(value: string): number {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?$/.exec(value)
  if (!match) return Number.NaN
  const [, y, m, d, h, min, s, fraction] = match
  const wholeMilliseconds = Date.UTC(Number(y), Number(m) - 1, Number(d), Number(h), Number(min), Number(s))
  const parsed = new Date(wholeMilliseconds)
  if (parsed.getUTCFullYear() !== Number(y) || parsed.getUTCMonth() !== Number(m) - 1 ||
    parsed.getUTCDate() !== Number(d) || parsed.getUTCHours() !== Number(h) ||
    parsed.getUTCMinutes() !== Number(min) || parsed.getUTCSeconds() !== Number(s)) return Number.NaN
  return wholeMilliseconds * 1000 + Number((fraction ?? '').padEnd(6, '0'))
}

export function contractTimeMs(value: string): number {
  return contractTimeUs(value) / 1000
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
