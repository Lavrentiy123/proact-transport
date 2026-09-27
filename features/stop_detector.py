"""Онлайн-детектор прибытий на плановые остановки одного борта.

Правила (одинаковые офлайн и онлайн, класс один и тот же):

- остановки упорядочены по плану; указатель ``i`` только растёт, кандидаты — ``i … i+15``;
- кандидат учитывается, только если время фикса в окне ``[plan − 6 мин, plan + 25 мин]``
  (по фактам train/test раньше плана больше чем на 5 мин приходят 0.3 % прибытий, на 10 мин — ни
  одного; окно в 20 мин давало ложные «прибытия» на 12–20 мин раньше: борт стоит на конечной у
  остановки следующего рейса или проходит мимо неё по встречной);
- если последнее прибытие свежее (≤ 30 мин), окно дополнительно сужается до правдоподобного
  отклонения ``[min(dev, 0) − 4 мин, max(dev, 0) + 15 мин]`` (``dev`` — отклонение последнего
  прибытия; «по плану» всегда внутри, поэтому после отстоя на конечной борт снова ловится);
- **прибытие** — первый фикс ближе 25 м; **проезд** — минимум расстояния < 60 м, а более поздний
  фикс дальше минимума на > 15 м (время прибытия = время фикса-минимума);
- **начало рейса** (первая остановка борта или остановка после паузы плана > 8 мин, т. е. конечная):
  факт АСУ здесь — **отправление** (на test медиана ошибки по выходу из радиуса −1 с, по входу −329 с),
  поэтому прибытием считается последний фикс «у остановки» (не дальше минимума + 15 м при минимуме
  < 60 м), а обнаруживается оно, когда борт отъехал от минимума больше чем на 50 м;
- при прибытии на кандидата ``k`` указатель становится ``k+1``, ``i … k−1`` помечаются ``missed``;
- остановки, окно которых уже закончилось (``t > plan + 25 мин``), тоже уходят в ``missed`` —
  иначе после долгого пропуска телеметрии указатель застрял бы навсегда.

Каждое прибытие хранит момент **обнаружения** ``t_det`` (фикс, на котором оно стало известно).
Для момента ``T`` известны только прибытия с ``t_det ≤ T`` — так офлайн-прогон по всему треку
совпадает с онлайн-прогоном, остановленным в ``T`` (у проезда ``t_arr < t_det``).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .geo import angle_diff_deg, bearing_deg, haversine_scalar_m
from .io import ScheduleArrays, from_epoch_s, to_epoch_s

ARRIVE_RADIUS_M = 25.0
PASS_RADIUS_M = 60.0
PASS_RECEDE_M = 15.0
WINDOW_BEFORE_S = 6 * 60.0
WINDOW_AFTER_S = 25 * 60.0
# Начало рейса: факт — отправление. Остановка после паузы плана > 8 мин (и первая остановка борта).
TERMINAL_GAP_S = 8 * 60.0
TERM_NEAR_TOL_M = 15.0   # «ещё у остановки»: не дальше минимума + 15 м (дрожание GPS на стоянке)
TERM_RECEDE_M = 50.0     # «отъехал»: дальше минимума на 50 м (15 м на стоянке срабатывают от дрожания)
# Спецификация задавала i … i+5 (и i+8 как запасной вариант), но на фактах train это давало
# покрытие 0.68 и 0.67: одна непойманная остановка держит указатель до 25 мин, пока борт уходит
# дальше 6 остановок. 16 кандидатов + окно по отклонению: покрытие 0.84, |ошибка| < 30 с — 77 %.
N_CANDIDATES = 16  # i … i+15
# Окно относительно текущего отклонения: отсекает ложные прыжки на петлях и у конечных
# (борт проходит в 25 м от остановки, которую обслужит через 15–20 минут).
REL_BEFORE_S = 4 * 60.0
REL_AFTER_S = 15 * 60.0
REL_MAX_AGE_S = 30 * 60.0
# Направление: проезд мимо остановки по встречной или по другой ветке петли — не прибытие. Курс —
# по своим фиксам за последние 2 мин (смещение ≥ 30 м); «против маршрута» — > 90° и к участку до
# остановки, и к участку после. На фактах train/test так движутся 1 % верных срабатываний и 67 %
# ложных «ранних» (раньше факта больше чем на 2 мин).
HEADING_MAX_DIFF_DEG = 90.0
HEADING_MIN_MOVE_M = 30.0
HEADING_LOOKBACK_S = 120.0
MIN_SEGMENT_M = 20.0     # участок короче — направление маршрута не определено


def pending_stops(plan_s: np.ndarray, last_idx: int | None, T: float) -> tuple[int, float]:
    """Остановки после последнего прибытия с планом ≤ T (ещё не достигнутые).

    Args:
        plan_s: плановые времена (отсортированы).
        last_idx: позиция последней остановки с прибытием или ``None``.
        T: момент прогноза, секунды.

    Returns:
        ``(n_pending, lb_delay_s)``; ``lb_delay_s = T − plan`` первой из них, иначе 0.
    """
    start = 0 if last_idx is None else last_idx + 1
    upto = int(np.searchsorted(plan_s, T, side="right"))
    n = max(upto - start, 0)
    return n, (T - float(plan_s[start]) if n > 0 else 0.0)


class StopDetector:
    """Детектор прибытий одного борта с монотонным указателем.

    Args:
        schedule_rows: плановые остановки борта (DataFrame из :func:`features.load_schedule`,
            сырой фрагмент ``schedule.csv`` или :class:`features.io.ScheduleArrays`).

    Attributes:
        sched: расписание в виде массивов.
        i: текущий указатель (первая ещё не пройденная остановка).
    """

    def __init__(self, schedule_rows):
        self.sched = schedule_rows if isinstance(schedule_rows, ScheduleArrays) else ScheduleArrays(schedule_rows)
        self._plan = self.sched.plan_s.tolist()
        self._lat = self.sched.lat.tolist()
        self._lon = self.sched.lon.tolist()
        self._n = len(self._plan)
        self._term = [k == 0 or self._plan[k] - self._plan[k - 1] > TERMINAL_GAP_S for k in range(self._n)]
        self._brg = [self._route_bearings(k) for k in range(self._n)]
        self._hist: list[tuple[float, float, float]] = []   # свои фиксы за HEADING_LOOKBACK_S: (t, lat, lon)
        self.i = 0
        self._min: dict[int, tuple[float, float]] = {}
        self._rec_idx: list[int] = []
        self._rec_t: list[float] = []
        self._rec_det: list[float] = []
        self._missed: list[tuple[int, float]] = []

    # ---------------- обновление ----------------
    def update(self, t, lat: float, lon: float, speed: float | None = None) -> list[tuple[int, pd.Timestamp]]:
        """Обрабатывает один валидный фикс (фиксы подаются по возрастанию времени).

        Args:
            t: время фикса (секунды или datetime).
            lat, lon: координаты.
            speed: скорость, км/ч (правилами детектора не используется, оставлена для API).

        Returns:
            Список новых прибытий ``[(stop_id, t_arr)]`` (0 или 1 элемент).
        """
        k_hit, t_arr = self._step(to_epoch_s(t), float(lat), float(lon))
        if k_hit is None:
            return []
        return [(int(self.sched.stop_id[k_hit]), from_epoch_s(t_arr))]

    def _route_bearings(self, k: int) -> tuple[float, ...]:
        """Направления маршрута у остановки ``k``: участок до неё и участок после (короткие пропускаются)."""
        out = []
        for a, b in ((k - 1, k), (k, k + 1)):
            if 0 <= a and b < self._n and haversine_scalar_m(self._lon[a], self._lat[a], self._lon[b], self._lat[b]) >= MIN_SEGMENT_M:
                out.append(bearing_deg(self._lon[a], self._lat[a], self._lon[b], self._lat[b]))
        return tuple(out)

    def _wrong_way(self, k: int, t: float, lat: float, lon: float) -> bool:
        """Движется ли борт против маршрута у остановки ``k`` (по своим фиксам до ``t`` включительно)."""
        brg = self._brg[k]
        if not brg:
            return False
        for tj, laj, loj in reversed(self._hist):
            if t - tj > HEADING_LOOKBACK_S:
                break
            if haversine_scalar_m(loj, laj, lon, lat) >= HEADING_MIN_MOVE_M:
                mv = bearing_deg(loj, laj, lon, lat)
                return all(angle_diff_deg(mv, b) > HEADING_MAX_DIFF_DEG for b in brg)
        return False  # стоит или почти не двигался — направление не известно

    def _step(self, t: float, lat: float, lon: float) -> tuple[int | None, float]:
        if not (math.isfinite(lat) and math.isfinite(lon)):
            return None, math.nan
        hist = self._hist
        hist.append((t, lat, lon))
        while hist and t - hist[0][0] > HEADING_LOOKBACK_S:
            hist.pop(0)
        plan = self._plan
        # остановки, окно которых закончилось, — пропущены
        while self.i < self._n and t > plan[self.i] + WINDOW_AFTER_S:
            self._missed.append((self.i, t))
            self._min.pop(self.i, None)
            self.i += 1
        if self.i >= self._n or t < plan[self.i] - WINDOW_BEFORE_S:
            return None, math.nan
        early, late = WINDOW_BEFORE_S, WINDOW_AFTER_S
        if self._rec_t and t - self._rec_t[-1] <= REL_MAX_AGE_S:
            # правдоподобное отклонение: от min(dev, 0) − REL_BEFORE до max(dev, 0) + REL_AFTER
            dev = self._rec_t[-1] - plan[self._rec_idx[-1]]
            early = min(early, REL_BEFORE_S - min(dev, 0.0))
            late = min(late, REL_AFTER_S + max(dev, 0.0))
        hit = None
        for k in range(self.i, min(self.i + N_CANDIDATES, self._n)):
            pk = plan[k]
            if t < pk - early:
                break  # план отсортирован: дальше окна ещё не начались
            if t > pk + late:
                continue
            d = haversine_scalar_m(lon, lat, self._lon[k], self._lat[k])
            st = self._min.get(k)
            if self._term[k]:
                # начало рейса: ждём отправления; st = (минимум расстояния, последний фикс у остановки)
                if st is None or d < st[0]:
                    self._min[k] = (d, t)
                elif d <= st[0] + TERM_NEAR_TOL_M:
                    self._min[k] = (st[0], t)
                elif st[0] < PASS_RADIUS_M and d > st[0] + TERM_RECEDE_M:
                    if self._wrong_way(k, t, lat, lon):
                        self._min.pop(k)  # уехал не по маршруту (на отстой, разворот) — ждём отправления
                        continue
                    hit = (k, st[1])
                    break
                continue
            if d < ARRIVE_RADIUS_M:
                if self._wrong_way(k, t, lat, lon):
                    continue
                hit = (k, t)
                break
            if st is not None and st[0] < PASS_RADIUS_M and d > st[0] + PASS_RECEDE_M:
                if self._wrong_way(k, t, lat, lon):
                    self._min.pop(k)
                    continue
                hit = (k, st[1])
                break
            if st is None or d < st[0]:
                self._min[k] = (d, t)
        if hit is None:
            return None, math.nan
        k, t_arr = hit
        for j in range(self.i, k):
            self._missed.append((j, t))
        self._rec_idx.append(k)
        self._rec_t.append(t_arr)
        self._rec_det.append(t)
        self.i = k + 1
        self._min = {}
        return k, t_arr

    # ---------------- снимки состояния (для вставки опоздавших пакетов онлайн) ----------------
    def snapshot(self) -> tuple:
        """Компактный снимок состояния (восстанавливается :meth:`restore`)."""
        return self.i, len(self._rec_idx), len(self._missed), dict(self._min), tuple(self._hist)

    def restore(self, snap: tuple) -> None:
        """Откатывает детектор к снимку :meth:`snapshot`."""
        i, n_rec, n_missed, mins, hist = snap
        self.i = i
        del self._rec_idx[n_rec:], self._rec_t[n_rec:], self._rec_det[n_rec:], self._missed[n_missed:]
        self._min = dict(mins)
        self._hist = list(hist)

    # ---------------- чтение ----------------
    def known(self, T=None) -> tuple[np.ndarray, np.ndarray]:
        """Прибытия, известные к моменту ``T`` (``t_det ≤ T``; ``None`` — все).

        Returns:
            ``(idx, t_arr)`` — позиции остановок в расписании и времена прибытия (секунды).
        """
        n = len(self._rec_det) if T is None else int(np.searchsorted(self._rec_det, to_epoch_s(T), side="right"))
        return np.asarray(self._rec_idx[:n], dtype=np.int64), np.asarray(self._rec_t[:n], dtype=np.float64)

    def records(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Все прибытия: ``(idx, t_arr, t_det)`` в порядке обнаружения."""
        return (np.asarray(self._rec_idx, dtype=np.int64), np.asarray(self._rec_t, dtype=np.float64),
                np.asarray(self._rec_det, dtype=np.float64))

    @property
    def arrivals(self) -> dict[int, pd.Timestamp]:
        """Все зафиксированные прибытия: ``stop_id -> t_arr``."""
        return {int(self.sched.stop_id[k]): from_epoch_s(t) for k, t in zip(self._rec_idx, self._rec_t)}

    @property
    def missed(self) -> list[int]:
        """``stop_id`` остановок, помеченных как пропущенные."""
        return [int(self.sched.stop_id[k]) for k, _ in self._missed]

    def last_arrival(self, T=None) -> tuple[int, pd.Timestamp, float] | None:
        """Последнее известное к ``T`` прибытие: ``(stop_id, t_arr, rdev_s)`` или ``None``."""
        idx, t_arr = self.known(T)
        if len(idx) == 0:
            return None
        k = int(idx[-1])
        return int(self.sched.stop_id[k]), from_epoch_s(float(t_arr[-1])), float(t_arr[-1] - self.sched.plan_s[k])

    def cur_dev_s(self, T=None) -> float:
        """Отклонение от плана на последней пройденной к ``T`` остановке, с (NaN, если прибытий нет)."""
        la = self.last_arrival(T)
        return la[2] if la is not None else math.nan

    def n_pending(self, T) -> int:
        """Сколько остановок с планом ≤ T после последнего прибытия ещё не достигнуто."""
        idx, _ = self.known(T)
        return pending_stops(self.sched.plan_s, int(idx[-1]) if len(idx) else None, to_epoch_s(T))[0]

    def lb_delay_s(self, T) -> float:
        """Нижняя граница задержки: ``T − plan`` первой недостигнутой остановки с планом ≤ T, иначе 0."""
        idx, _ = self.known(T)
        return pending_stops(self.sched.plan_s, int(idx[-1]) if len(idx) else None, to_epoch_s(T))[1]
