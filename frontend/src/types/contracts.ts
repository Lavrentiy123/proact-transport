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

/** Reject malformed live frames before they reach rendering components. */
export function parseWsMessage(raw: unknown): WsMessage | null {
  const object = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null
  const number = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
  const date = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d/.test(value)
  const forecast = (value: unknown): boolean => object(value) &&
    number(value.target_stop_id) && typeof value.target_stop_name === 'string' && date(value.target_time_plan) &&
    number(value.delay_pred_s) && number(value.delay_q10_s) && number(value.delay_q90_s) &&
    number(value.p_late) && ['green', 'yellow', 'red'].includes(String(value.risk)) &&
    object(value.cause) && typeof value.cause.text === 'string' &&
    typeof value.cause.evidence === 'string' && number(value.cause.confidence)
  const vehicle = (value: unknown): boolean => object(value) &&
    number(value.tr_id) && number(value.lat) && number(value.lon) &&
    typeof value.stale === 'boolean' && number(value.last_seen_s) &&
    (value.forecast == null || forecast(value.forecast))
  const alert = (value: unknown): boolean => object(value) &&
    typeof value.alert_id === 'string' && number(value.tr_id) &&
    number(value.priority) && typeof value.status === 'string' &&
    forecast(value.forecast) &&
    (value.recommendation == null || (object(value.recommendation) && typeof value.recommendation.text === 'string'))

  if (!object(raw) || !['snapshot', 'alert', 'status'].includes(String(raw.type)) || !date(raw.sim_time)) return null
  if (raw.vehicles != null && (!Array.isArray(raw.vehicles) || !raw.vehicles.every(vehicle))) return null
  if (raw.alerts != null && (!Array.isArray(raw.alerts) || !raw.alerts.every(alert))) return null
  if (raw.status != null && (!object(raw.status) || !['LIVE', 'DEGRADED', 'REPLAY'].includes(String(raw.status.mode)))) return null
  return raw as unknown as WsMessage
}
