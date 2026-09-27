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

type PluralForms = { one: string; few: string; many: string }
const ruPlural = new Intl.PluralRules('ru-RU')

/** «1 предупреждение», «3 предупреждения», «5 предупреждений»: форма слова по числу. */
export function plural(count: number, forms: PluralForms): string {
  const rule = ruPlural.select(count)
  return rule === 'one' ? forms.one : rule === 'few' ? forms.few : forms.many
}

export const ALERT_FORMS: PluralForms = { one: 'предупреждение', few: 'предупреждения', many: 'предупреждений' }

/** «план через 4 мин» или, если плановое время уже прошло, «план прошёл 2 мин назад». */
export function planCountdown(secondsToPlan: number | null | undefined): string {
  if (secondsToPlan == null || !Number.isFinite(secondsToPlan)) return 'план —'
  const minutes = Math.max(1, Math.round(Math.abs(secondsToPlan) / 60))
  return secondsToPlan >= 0 ? `план через ${minutes} мин` : `план прошёл ${minutes} мин назад`
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`
}

/** Название остановки. У 17,5 % строк расписания датасета нет адреса, а stop_id — id строки расписания,
 * а не номер остановки, поэтому номер не показываем. */
export function stopLabel(name: string | null | undefined, _stopId?: number | null): string {
  return (name ?? '').trim() || 'ост. без адреса'
}
