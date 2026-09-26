"""Общие контракты «ПроАкт.Транспорт» (v0, заморожены 26.09).

Единый источник правды для трёх модулей:
- backend отдаёт эти модели в REST и WebSocket;
- frontend строит по ним типы и моки (примеры в ``contracts/examples/``);
- ml-core принимает ``PredictRequest`` и отвечает ``PredictResponse``.

Менять поля можно только по договорённости всей команды: добавлять новые
необязательные поля — свободно, переименовывать и удалять — через интегратора.
Время везде ISO-8601 без таймзоны, в часовом поясе датасета (Москва).
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Risk(StrEnum):
    green = "green"    # прогноз задержки < 120 с (порог "late" из labels)
    yellow = "yellow"  # 120–300 с или неуверенный прогноз
    red = "red"        # > 300 с или P(задержка > 120 с) >= 0.8


class Quality(StrEnum):
    full = "full"          # свежая телеметрия, основная модель
    degraded = "degraded"  # борт молчит > 30 с, позиция экстраполирована
    fallback = "fallback"  # поток или ml-core недоступны, прогноз по расписанию


class Mode(StrEnum):
    live = "LIVE"          # идут NDTP-пакеты
    degraded = "DEGRADED"  # нет пакетов > 15 с
    replay = "REPLAY"      # демо-воспроизведение исторического дня


class Cause(BaseModel):
    code: str = Field(examples=["congestion"])  # congestion|dwell|accumulated|hard_segment|early|low_data
    text: str = Field(examples=["Затор на перегоне"])
    evidence: str = Field(examples=["4 км/ч за 5 мин (норма 18), стоит 3:40 вне остановки"])
    confidence: float = Field(ge=0, le=1)


class Forecast(BaseModel):
    target_stop_id: int
    target_stop_name: str
    target_time_plan: datetime
    issued_at: datetime
    lead_s: int = Field(ge=600, le=900, description="target_time_plan - issued_at, горизонт 10–15 мин")
    delay_pred_s: float
    delay_q10_s: float
    delay_q90_s: float
    p_late: float = Field(ge=0, le=1, description="P(задержка > 120 с)")
    risk: Risk
    quality: Quality
    cause: Cause
    model_version: str


class Recommendation(BaseModel):
    action: str = Field(examples=["speed_advice"])  # speed_advice|hold|reserve
    text: str = Field(examples=["Держать среднюю скорость 24 км/ч до ост. «Ул. Гарибальди»"])
    target_speed_kmh: float | None = None  # для speed_advice
    hold_s: int | None = Field(None, ge=0, le=120)  # для hold (межрейсовая стоянка)
    stop_id: int | None = None
    expected_delay_after_s: float | None = None


class VehicleState(BaseModel):
    tr_id: int
    lat: float
    lon: float
    speed_kmh: float
    heading: float
    cur_dev_s: float | None = Field(None, description="отклонение на последней пройденной остановке (онлайн)")
    seg_speed_kmh: float | None = Field(None, description="средняя скорость на текущем перегоне")
    dwell_s: float | None = Field(None, description="текущее время простоя")
    last_seen_s: float = Field(description="сколько секунд назад пришёл последний пакет")
    stale: bool
    is_opening_or_closing_trip: bool = False  # первый/последний рейс: алерт важнее (QA 34:08)
    forecast: Forecast | None = None


class Alert(BaseModel):
    alert_id: str
    created_at: datetime
    tr_id: int
    risk: Risk
    priority: int = Field(description="чем больше, тем выше в ленте")
    title: str = Field(examples=["Борт 131672: +6 мин к ост. «Ул. Гарибальди» через 12 мин"])
    forecast: Forecast
    recommendation: Recommendation | None = None
    status: str = "active"  # active|applied|dismissed|resolved


class StopOnTrack(BaseModel):
    """Плановая остановка борта: основа линии на карте и диаграммы Марея."""
    stop_id: int
    name: str
    lat: float
    lon: float
    seq: int
    time_plan: datetime
    time_fact: datetime | None = None      # из онлайн-детектора прибытий
    time_forecast: datetime | None = None  # план + прогноз задержки


class TrackResponse(BaseModel):
    tr_id: int
    stops: list[StopOnTrack]
    trail: list[tuple[datetime, float, float]] = Field(description="последние точки GPS: (t, lat, lon)")


class SystemStatus(BaseModel):
    mode: Mode
    sim_time: datetime
    replay_speed: float
    ndtp_sessions: int
    last_packet_age_s: float
    ml_core_ok: bool
    model_version: str


class HorizonMetrics(BaseModel):
    """Доказательство для критерия 2: прогнозы строго за 10–15 минут."""
    forecasts_total: int
    share_lead_in_window: float  # доля прогнозов с lead_s ∈ [600, 900]
    resolved_total: int          # сколько прогнозов уже сверено с фактом
    online_mae_model_s: float | None
    online_mae_baseline_s: float | None  # бейзлайн «задержка = cur_dev»


class ActionRequest(BaseModel):
    alert_id: str
    action: str  # apply|dismiss
    comment: str | None = None


class ActionResponse(BaseModel):
    alert_id: str
    status: str
    driver_message: str   # что ушло водителю (канал NDTP «диспетчер ↔ водитель», в демо эмулируется)
    driver_reply: str | None = None  # "успеваю" | "не успеваю" | "нештатная ситуация"


class WhatIfRequest(BaseModel):
    scenario: str = Field(examples=["hold", "reserve"])
    tr_id: int
    stop_id: int | None = None
    hold_s: int = Field(0, ge=0, le=120)


class WhatIfResponse(BaseModel):
    delay_before_s: float
    delay_after_s: float
    headways_before_s: list[float] = []
    headways_after_s: list[float] = []
    ewt_before_min: float | None = None
    ewt_after_min: float | None = None
    note: str = ""


class WsMessage(BaseModel):
    """Сообщение WebSocket /ws/live, 1 раз в секунду."""
    type: str  # snapshot|alert|status
    sim_time: datetime
    vehicles: list[VehicleState] | None = None
    alerts: list[Alert] | None = None
    status: SystemStatus | None = None


# ---------- backend -> ml-core ----------

class PredictRow(BaseModel):
    tr_id: int
    features: dict[str, float | None]  # имена признаков: FEATURE_NAMES из пакета features/


class PredictRequest(BaseModel):
    model: str = "online"  # online|sched (fallback без телеметрии)
    rows: list[PredictRow]


class PredictResult(BaseModel):
    tr_id: int
    delta_pred_s: float  # прогноз изменения задержки относительно cur_dev
    delay_pred_s: float
    delay_q10_s: float
    delay_q90_s: float
    p_late: float
    cause_code: str
    cause_confidence: float
    group_contrib_s: dict[str, float] = {}


class PredictResponse(BaseModel):
    model_version: str
    latency_ms: float
    results: list[PredictResult]
