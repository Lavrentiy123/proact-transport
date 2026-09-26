"""Риск, причина с доказательством, рекомендация и алерты с гистерезисом.

Правила — ``contracts/README.md`` («Логика тика backend»):

- риск: green < 120 с ≤ yellow < 300 с ≤ red, либо red при ``p_late ≥ 0.8``;
- алерт поднимается на red и снимается, когда прогноз < 200 с два тика подряд;
- рекомендация: опаздывает → ``speed_advice`` (оставшаяся дистанция / оставшееся плановое время),
  опережает → ``hold`` 30–120 с, red на первом или последнем рейсе → ``reserve``.

Ключ алерта — ``tr_id``: целевая остановка сдвигается вместе с окном (now+10, now+15] примерно раз в
минуту, и алерт по ``(tr_id, остановка)`` пересоздавался бы (``docs/RASTSOV_BRIEF.md`` §5.2 п. 6).
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime

from contracts.schemas import Alert, Cause, Forecast, Recommendation, Risk
from features import to_epoch_s

RED_S, YELLOW_S, P_LATE_RED = 300.0, 120.0, 0.8
CLEAR_S, CLEAR_TICKS = 200.0, 2
EARLY_S = -60.0
MAX_ADVICE_KMH = 45.0

CAUSE_TEXT = {
    "congestion": "Затор на перегоне",
    "dwell": "Долгая стоянка на остановке",
    "accumulated": "Накопленное отставание",
    "hard_segment": "Тяжёлый участок впереди",
    "early": "Опережение графика",
    "low_data": "Мало свежих данных",
}


def fmt_delay(s: float | None) -> str:
    """``372`` → ``+6:12``; ``-95`` → ``−1:35``."""
    if s is None or not math.isfinite(s):
        return "н/д"
    sign = "+" if s >= 0 else "−"
    s = abs(int(round(s)))
    return f"{sign}{s // 60}:{s % 60:02d}"


def fmt_mmss(s: float | None) -> str:
    if s is None or not math.isfinite(s):
        return "н/д"
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


def _f(feats: dict, key: str) -> float | None:
    v = feats.get(key) if feats else None
    return float(v) if v is not None and math.isfinite(float(v)) else None


def risk_of(delay_pred_s: float, p_late: float) -> Risk:
    """Цвет риска по порогам контракта."""
    if delay_pred_s >= RED_S or p_late >= P_LATE_RED:
        return Risk.red
    if delay_pred_s >= YELLOW_S:
        return Risk.yellow
    return Risk.green


def build_cause(code: str, confidence: float, feats: dict, derived: dict, last_stop_name: str | None,
                target_name: str, horizon_s: float) -> Cause:
    """Текст причины и числовое доказательство из признаков буфера и ``OnlineVehicle.derived()``."""
    v5 = _f(feats, "v_mean_5m")
    out5 = _f(feats, "stop_out_zone_s_5m")
    in5 = _f(feats, "stop_in_zone_s_5m")
    tel = _f(feats, "tel_age_s")
    route = _f(feats, "route_dist_m") or _f(feats, "dist_to_target_m")
    cur = derived.get("cur_dev_s")
    dwell = derived.get("dwell_s")
    seg = derived.get("seg_speed_kmh")
    at = f" на ост. «{last_stop_name}»" if last_stop_name else ""
    if code == "congestion":
        ev = f"{v5:.0f} км/ч за 5 мин" if v5 is not None else "скорость н/д"
        if out5:
            ev += f", стоит {fmt_mmss(out5)} вне остановок"
    elif code == "dwell":
        ev = f"стоит у остановки {fmt_mmss(in5)} за 5 мин"
        if dwell:
            ev += f", текущая стоянка {fmt_mmss(dwell)}"
    elif code == "accumulated":
        ev = f"уже {fmt_delay(cur)}{at}" if cur is not None else "отставание по последним остановкам"
    elif code == "hard_segment":
        need = route / horizon_s * 3.6 if route and horizon_s > 0 else None
        ev = (f"до «{target_name}» {route / 1000:.1f} км за {fmt_mmss(horizon_s)}: нужно {need:.0f} км/ч"
              if need is not None else "длинный перегон до целевой остановки")
        if seg is not None and math.isfinite(seg):
            ev += f", на перегоне {seg:.0f} км/ч"
    elif code == "early":
        ev = f"{fmt_delay(cur)}{at}" if cur is not None else "прогноз раньше плана"
    else:   # low_data
        ev = f"нет данных {tel:.0f} с" if tel is not None else "нет прибытий на остановки"
    return Cause(code=code, text=CAUSE_TEXT.get(code, code), evidence=ev,
                 confidence=float(min(1.0, max(0.0, confidence))))


def recommend(fc: Forecast, feats: dict, opening_or_closing: bool) -> Recommendation | None:
    """Рекомендация по правилам контракта (не ML)."""
    remain_s = fc.lead_s
    name = fc.target_stop_name or str(fc.target_stop_id)
    if fc.risk == Risk.red and opening_or_closing:
        return Recommendation(action="reserve", stop_id=fc.target_stop_id,
                              text=f"Первый/последний рейс, прогноз {fmt_delay(fc.delay_pred_s)}: рассмотреть выпуск "
                                   f"резервного ТС до ост. «{name}»")
    if fc.delay_pred_s >= YELLOW_S:
        route = _f(feats, "route_dist_m") or _f(feats, "dist_to_target_m")
        if route is None or remain_s <= 0:
            return None
        v = route / remain_s * 3.6
        if v > MAX_ADVICE_KMH:
            return Recommendation(action="speed_advice", stop_id=fc.target_stop_id, target_speed_kmh=round(v, 1),
                                  text=f"Нагнать скоростью нельзя (нужно {v:.0f} км/ч до ост. «{name}»): "
                                       f"предупредить пассажиров, рассмотреть резерв")
        return Recommendation(action="speed_advice", stop_id=fc.target_stop_id, target_speed_kmh=round(v, 1),
                              text=f"Держать среднюю скорость {v:.0f} км/ч до ост. «{name}»")
    if fc.delay_pred_s < EARLY_S:
        hold = int(min(120, max(30, round(-fc.delay_pred_s))))
        return Recommendation(action="hold", stop_id=fc.target_stop_id, hold_s=hold,
                              text=f"Межрейсовая стоянка {hold} с до ост. «{name}» (опережение "
                                   f"{fmt_delay(fc.delay_pred_s)})")
    return None


def priority_of(fc: Forecast, opening_or_closing: bool) -> int:
    """Чем больше, тем выше в ленте: прогноз опоздания + 300 для первого/последнего рейса (QA 34:08)."""
    return int(round(max(fc.delay_pred_s, 0.0))) + (300 if opening_or_closing else 0)


def title_of(tr_id: int, fc: Forecast) -> str:
    return (f"Борт {tr_id}: {fmt_delay(fc.delay_pred_s)} к ост. «{fc.target_stop_name}» "
            f"через {max(1, round(fc.lead_s / 60))} мин")


class AlertBook:
    """Активные алерты по ``tr_id`` с гистерезисом и архив снятых."""

    def __init__(self, keep_closed: int = 200):
        self.active: dict[int, Alert] = {}
        self.closed: deque[Alert] = deque(maxlen=keep_closed)
        self._calm: dict[int, int] = {}        # tr_id -> тиков подряд с прогнозом < 200 с (или без прогноза)
        self._suppressed: set[int] = set()     # решено диспетчером — не поднимать, пока не успокоится
        self.raised_total = 0

    def reset(self) -> None:
        self.active.clear()
        self.closed.clear()
        self._calm.clear()
        self._suppressed.clear()

    def update(self, tr_id: int, fc: Forecast | None, rec: Recommendation | None, opening_or_closing: bool,
               now: datetime) -> Alert | None:
        """Обновляет состояние алерта борта по прогнозу тика; возвращает активный алерт или ``None``."""
        calm = fc is None or fc.delay_pred_s < CLEAR_S
        self._calm[tr_id] = self._calm.get(tr_id, 0) + 1 if calm else 0
        if self._calm[tr_id] >= CLEAR_TICKS:
            self._suppressed.discard(tr_id)
            a = self.active.pop(tr_id, None)
            if a is not None:
                a.status = "resolved"
                self.closed.append(a)
            return None
        a = self.active.get(tr_id)
        if fc is None:
            return a
        if a is None:
            if fc.risk != Risk.red or tr_id in self._suppressed:
                return None
            a = Alert(alert_id=f"{tr_id}-{int(to_epoch_s(now))}", created_at=now, tr_id=tr_id, risk=fc.risk,
                      priority=priority_of(fc, opening_or_closing), title=title_of(tr_id, fc), forecast=fc,
                      recommendation=rec, status="active")
            self.active[tr_id] = a
            self.raised_total += 1
            return a
        a.risk, a.forecast, a.recommendation = fc.risk, fc, rec
        a.priority, a.title = priority_of(fc, opening_or_closing), title_of(tr_id, fc)
        return a

    def find(self, alert_id: str) -> Alert | None:
        for a in list(self.active.values()) + list(self.closed):
            if a.alert_id == alert_id:
                return a
        return None

    def decide(self, alert_id: str, status: str) -> Alert | None:
        """Решение диспетчера: алерт уходит из активных, повторно не поднимается до «успокоения» борта."""
        a = self.find(alert_id)
        if a is None:
            return None
        a.status = status
        if self.active.get(a.tr_id) is a:
            self.active.pop(a.tr_id)
            self.closed.append(a)
            self._suppressed.add(a.tr_id)
        return a
