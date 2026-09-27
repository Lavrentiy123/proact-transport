import { contractTimeUs } from '../utils/time'

/** Mirror of contracts/schemas.py. Times are ISO-8601 in Moscow local time. */
export type Risk = 'green' | 'yellow' | 'red'
export type Quality = 'full' | 'degraded' | 'fallback'
export type Mode = 'LIVE' | 'DEGRADED' | 'REPLAY'

export interface Cause {
  code: string
  text: string
  evidence: string
  confidence: number
}

export interface Forecast {
  target_stop_id: number
  target_stop_name: string
  target_time_plan: string
  issued_at: string
  lead_s: number
  delay_pred_s: number
  delay_q10_s: number
  delay_q90_s: number
  p_late: number
  risk: Risk
  quality: Quality
  cause: Cause
  model_version: string
}

export interface Recommendation {
  action: string
  text: string
  target_speed_kmh: number | null
  hold_s: number | null
  stop_id: number | null
  expected_delay_after_s: number | null
}

export interface VehicleState {
  tr_id: number
  lat: number
  lon: number
  speed_kmh: number
  heading: number
  cur_dev_s: number | null
  seg_speed_kmh: number | null
  dwell_s: number | null
  last_seen_s: number
  stale: boolean
  is_opening_or_closing_trip: boolean
  forecast: Forecast | null
}

export interface Alert {
  alert_id: string
  created_at: string
  tr_id: number
  risk: Risk
  priority: number
  title: string
  forecast: Forecast
  recommendation: Recommendation | null
  status: string
}

export interface StopOnTrack {
  stop_id: number
  name: string
  lat: number
  lon: number
  seq: number
  time_plan: string
  time_fact: string | null
  time_forecast: string | null
}

export interface TrackResponse {
  tr_id: number
  stops: StopOnTrack[]
  /** (t, lat, lon) */
  trail: [string, number, number][]
}

export interface SystemStatus {
  mode: Mode
  sim_time: string
  replay_speed: number
  ndtp_sessions: number
  last_packet_age_s: number
  ml_core_ok: boolean
  model_version: string
}

export interface WsMessage {
  type: 'snapshot' | 'alert' | 'status'
  sim_time: string
  vehicles?: VehicleState[] | null
  alerts?: Alert[] | null
  status?: SystemStatus | null
}

export interface HorizonMetrics {
  forecasts_total: number
  share_lead_in_window: number
  resolved_total: number
  online_mae_model_s: number | null
  online_mae_baseline_s: number | null
}

export interface ActionResponse {
  alert_id: string
  status: string
  driver_message: string
  driver_reply: string | null
}

/** Backend computes status after vehicles and alerts on a running clock, so at
 * REPLAY_SPEED=10 its sim_time is milliseconds ahead of the frame time. */
const STATUS_CLOCK_SKEW_US = 2_000_000

/** Reject malformed live frames before they reach rendering components. */
export function parseWsMessage(raw: unknown): WsMessage | null {
  const object = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
  const number = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
  const integer = (value: unknown): value is number => number(value) && Number.isSafeInteger(value)
  const optionalNumber = (value: unknown) => value == null || number(value)
  const probability = (value: unknown) => number(value) && value >= 0 && value <= 1
  const risk = (value: unknown) => value === 'green' || value === 'yellow' || value === 'red'
  const date = (value: unknown): value is string => {
    return typeof value === 'string' && Number.isFinite(contractTimeUs(value))
  }
  const cause = (value: unknown) => object(value) &&
    typeof value.code === 'string' && typeof value.text === 'string' &&
    typeof value.evidence === 'string' && probability(value.confidence)
  const forecast = (value: unknown): boolean => object(value) &&
    integer(value.target_stop_id) && typeof value.target_stop_name === 'string' &&
    date(value.target_time_plan) && date(value.issued_at) &&
    integer(value.lead_s) && value.lead_s >= 600 && value.lead_s <= 900 &&
    number(value.delay_pred_s) && number(value.delay_q10_s) && number(value.delay_q90_s) &&
    value.delay_q10_s <= value.delay_q90_s && probability(value.p_late) &&
    risk(value.risk) && ['full', 'degraded', 'fallback'].includes(String(value.quality)) &&
    cause(value.cause) && typeof value.model_version === 'string'
  const recommendation = (value: unknown) => object(value) &&
    typeof value.action === 'string' && typeof value.text === 'string' &&
    optionalNumber(value.target_speed_kmh) && optionalNumber(value.hold_s) &&
    (value.stop_id == null || integer(value.stop_id)) && optionalNumber(value.expected_delay_after_s)
  const vehicle = (value: unknown): boolean => object(value) &&
    integer(value.tr_id) && number(value.lat) && number(value.lon) &&
    number(value.speed_kmh) && number(value.heading) &&
    optionalNumber(value.cur_dev_s) && optionalNumber(value.seg_speed_kmh) && optionalNumber(value.dwell_s) &&
    number(value.last_seen_s) && value.last_seen_s >= 0 &&
    typeof value.stale === 'boolean' &&
    (value.is_opening_or_closing_trip == null || typeof value.is_opening_or_closing_trip === 'boolean') &&
    (value.forecast == null || forecast(value.forecast))
  const alert = (value: unknown): boolean => object(value) &&
    typeof value.alert_id === 'string' && date(value.created_at) && integer(value.tr_id) &&
    risk(value.risk) && integer(value.priority) && typeof value.title === 'string' &&
    typeof value.status === 'string' && forecast(value.forecast) &&
    (value.recommendation == null || recommendation(value.recommendation))
  const status = (value: unknown) => object(value) &&
    ['LIVE', 'DEGRADED', 'REPLAY'].includes(String(value.mode)) && date(value.sim_time) &&
    number(value.replay_speed) && integer(value.ndtp_sessions) &&
    number(value.last_packet_age_s) && typeof value.ml_core_ok === 'boolean' &&
    typeof value.model_version === 'string'

  if (!object(raw) || !['snapshot', 'alert', 'status'].includes(String(raw.type)) || !date(raw.sim_time)) return null
  if (raw.vehicles != null && (!Array.isArray(raw.vehicles) || !raw.vehicles.every(vehicle) ||
    new Set(raw.vehicles.map((item) => item.tr_id)).size !== raw.vehicles.length)) return null
  if (raw.alerts != null && (!Array.isArray(raw.alerts) || !raw.alerts.every(alert) ||
    new Set(raw.alerts.map((item) => item.alert_id)).size !== raw.alerts.length)) return null
  if (raw.status != null && !status(raw.status)) return null
  if (raw.status != null &&
    contractTimeUs((raw.status as { sim_time: string }).sim_time) - contractTimeUs(raw.sim_time) > STATUS_CLOCK_SKEW_US) return null
  const issuedInFuture = (item: { forecast?: { issued_at?: string } | null }) =>
    item.forecast && contractTimeUs(item.forecast.issued_at ?? '') > contractTimeUs(raw.sim_time as string)
  if (Array.isArray(raw.vehicles) && raw.vehicles.some(issuedInFuture)) return null
  if (Array.isArray(raw.alerts) && raw.alerts.some(issuedInFuture)) return null
  if (Array.isArray(raw.alerts) && raw.alerts.some((item) => contractTimeUs(item.created_at) > contractTimeUs(raw.sim_time as string))) return null
  return raw as unknown as WsMessage
}
