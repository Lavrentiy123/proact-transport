"""Состояние одного борта на потоке — класс, который backend использует как есть.

Пример::

    from features import OnlineVehicle, load_schedule
    sched = load_schedule("data/test/schedule.csv")
    veh = OnlineVehicle(sched[sched.tr_id == 131672])
    veh.push(t, lat, lon, speed, heading, valid)      # на каждый NDTP-пакет
    tgt = veh.target_at(now)                          # (stop_id, time_plan) или None
    feats = veh.features_at(now)                      # dict FEATURE_NAMES или None
"""

from __future__ import annotations

import bisect
import math

import numpy as np
import pandas as pd

from .build import STOP_SPEED_KMH, features_from_arrays, in_zone_flags
from .io import ScheduleArrays, from_epoch_s, to_epoch_s
from .stop_detector import StopDetector

BUFFER_S = 35 * 60.0          # держим чуть больше окна признаков (30 мин)
TARGET_MIN_LEAD_S, TARGET_MAX_LEAD_S = 600.0, 900.0
TRIP_EDGE_S = 60 * 60.0       # «первый/последний рейс»: первые/последние 60 мин расписания


class OnlineVehicle:
    """Буфер телеметрии борта за последние 30 минут + детектор прибытий.

    Фиксы можно подавать не по порядку (пакеты ``is_hist_data``): опоздавший фикс, который не
    старше буфера, встаёт на своё место, а детектор перепроигрывается с этого места — результат
    тот же, что при подаче по времени (и что офлайн в :func:`features.build_features_batch`).

    Args:
        schedule_rows: плановые остановки борта (фрагмент :func:`features.load_schedule`).
        tr_id: номер борта (для логов и ответов).
    """

    def __init__(self, schedule_rows, tr_id: int | None = None):
        self.tr_id = tr_id
        self.sched = schedule_rows if isinstance(schedule_rows, ScheduleArrays) else ScheduleArrays(schedule_rows)
        self.detector = StopDetector(self.sched)
        self._t: list[float] = []
        self._lat: list[float] = []
        self._lon: list[float] = []
        self._spd: list[float] = []
        self._hdg: list[float] = []
        self._zone: list[bool] = []
        self._snap: list[tuple] = []   # состояние детектора перед применением фикса
        self.last_seen_s: float = math.nan
        self.n_dropped_late = 0
        self._pruned_until = -math.inf  # время последнего фикса, вытесненного из буфера

    # ---------------- приём пакетов ----------------
    def push(self, t, lat: float, lon: float, speed: float, heading: float = math.nan,
             valid: bool = True) -> list[tuple[int, pd.Timestamp]]:
        """Принимает один пакет телеметрии.

        Args:
            t: время фикса (datetime / ISO-строка / секунды).
            lat, lon: координаты.
            speed: скорость, км/ч.
            heading: курс, градусы.
            valid: валидность координат; невалидный фикс обновляет только ``last_seen``.

        Returns:
            Новые прибытия на остановки ``[(stop_id, t_arr)]``.
        """
        t_s = to_epoch_s(t)
        self.last_seen_s = t_s if math.isnan(self.last_seen_s) else max(self.last_seen_s, t_s)
        lat, lon = float(lat), float(lon)
        if not valid or not (math.isfinite(lat) and math.isfinite(lon)):
            return []
        spd = float(speed) if speed is not None else math.nan
        hdg = float(heading) if heading is not None else math.nan
        zone = bool(in_zone_flags(np.array([lat]), np.array([lon]), self.sched)[0])
        if not self._t or t_s > self._t[-1]:
            new = self._append(t_s, lat, lon, spd, hdg, zone)
        else:
            pos = bisect.bisect_left(self._t, t_s)
            if pos < len(self._t) and self._t[pos] == t_s:
                return []  # дубль по времени — оставляем первый
            if t_s <= self._pruned_until:
                self.n_dropped_late += 1  # старше буфера: детектор уже не перепроиграть
                return []
            new = self._insert(pos, t_s, lat, lon, spd, hdg, zone)
        self._prune()
        return [(int(self.sched.stop_id[k]), from_epoch_s(ta)) for k, ta in new]

    def _append(self, t_s, lat, lon, spd, hdg, zone) -> list[tuple[int, float]]:
        self._snap.append(self.detector.snapshot())
        self._t.append(t_s), self._lat.append(lat), self._lon.append(lon)
        self._spd.append(spd), self._hdg.append(hdg), self._zone.append(zone)
        k, ta = self.detector._step(t_s, lat, lon)
        return [] if k is None else [(k, ta)]

    def _insert(self, pos, t_s, lat, lon, spd, hdg, zone) -> list[tuple[int, float]]:
        n_before = len(self.detector._rec_idx)
        self.detector.restore(self._snap[pos])
        n_restored = len(self.detector._rec_idx)
        for arr, v in ((self._t, t_s), (self._lat, lat), (self._lon, lon), (self._spd, spd),
                       (self._hdg, hdg), (self._zone, zone)):
            arr.insert(pos, v)
        self._snap.insert(pos, None)
        for j in range(pos, len(self._t)):
            self._snap[j] = self.detector.snapshot()
            self.detector._step(self._t[j], self._lat[j], self._lon[j])
        # «новые» — прибытия, которых не было до вставки
        idx, t_arr, _ = self.detector.records()
        return [(int(idx[m]), float(t_arr[m])) for m in range(max(n_before, n_restored), len(idx))]

    def _prune(self) -> None:
        cut = bisect.bisect_left(self._t, self._t[-1] - BUFFER_S)
        if cut > 0:
            self._pruned_until = self._t[cut - 1]
            for arr in (self._t, self._lat, self._lon, self._spd, self._hdg, self._zone, self._snap):
                del arr[:cut]

    # ---------------- прогнозная точка ----------------
    def target_at(self, T) -> tuple[int, pd.Timestamp] | None:
        """Первая плановая остановка с ``time_plan ∈ (T + 10 мин, T + 15 мин]``.

        Returns:
            ``(stop_id, time_plan)`` или ``None`` — тогда прогноз не строится (критерий 2).
        """
        T_s = to_epoch_s(T)
        plan = self.sched.plan_s
        k = int(np.searchsorted(plan, T_s + TARGET_MIN_LEAD_S, side="right"))
        if k < len(plan) and plan[k] <= T_s + TARGET_MAX_LEAD_S:
            return int(self.sched.stop_id[k]), from_epoch_s(float(plan[k]))
        return None

    def _arrays(self):
        return (np.asarray(self._t, dtype=np.float64), np.asarray(self._lat, dtype=np.float64),
                np.asarray(self._lon, dtype=np.float64), np.asarray(self._spd, dtype=np.float64),
                np.asarray(self._zone, dtype=bool))

    def features_at(self, T, target: tuple[int, object] | None = None) -> dict[str, float] | None:
        """Признаки для прогноза в момент ``T`` (``cur_dev_s`` — восстановленное детектором).

        Args:
            T: момент прогноза (обычно время симуляции).
            target: ``(stop_id, time_plan)``; по умолчанию :meth:`target_at`.

        Returns:
            ``dict`` :data:`features.FEATURE_NAMES` или ``None``, если в окне 10–15 мин нет остановки.
        """
        tgt = target if target is not None else self.target_at(T)
        if tgt is None:
            return None
        T_s = to_epoch_s(T)
        t, lat, lon, spd, zone = self._arrays()
        arr_idx, arr_t = self.detector.known(T_s)
        return features_from_arrays(T_s, t, lat, lon, spd, self.sched, self.sched.index_of.get(int(tgt[0])),
                                    to_epoch_s(tgt[1]), arr_idx, arr_t, None, zone)

    # ---------------- производные для VehicleState ----------------
    def derived(self, T) -> dict[str, float | None]:
        """Признаки состояния для ``VehicleState`` (критерий 3).

        Returns:
            ``{"cur_dev_s", "seg_speed_kmh", "dwell_s"}``: отклонение на последней пройденной
            остановке; средняя скорость с последнего прибытия; длительность текущей стоянки.
            ``None`` — нет данных.
        """
        T_s = to_epoch_s(T)
        t, _, _, spd, _ = self._arrays()
        hi = int(np.searchsorted(t, T_s, side="right"))
        t, spd = t[:hi], spd[:hi]
        la = self.detector.last_arrival(T_s)
        cur = la[2] if la is not None else None
        seg = None
        if len(t):
            since = to_epoch_s(la[1]) if la is not None else T_s - 300.0
            m = t > since
            if m.any():
                seg = float(np.nanmean(spd[m]))
        dwell = None
        if len(t):
            j = len(t)
            while j > 0 and spd[j - 1] < STOP_SPEED_KMH:
                j -= 1
            dwell = 0.0 if j == len(t) else float(T_s - t[j])
        return {"cur_dev_s": cur, "seg_speed_kmh": seg, "dwell_s": dwell}

    def is_opening_or_closing_trip(self, T) -> bool:
        """ЭВРИСТИКА: целевая остановка в первые или последние 60 минут расписания борта за день.

        Настоящих рейсов (``route_id``/``trip_id``) в данных нет, поэтому «первый/последний рейс»
        приближаем по времени. Опоздания здесь важнее для перевозчика (QA-сессия, 34:08).
        """
        tgt = self.target_at(T)
        if tgt is None or len(self.sched) == 0:
            return False
        p = to_epoch_s(tgt[1])
        first, last = float(self.sched.plan_s[0]), float(self.sched.plan_s[-1])
        return p <= first + TRIP_EDGE_S or p >= last - TRIP_EDGE_S

    def stop_name(self, stop_id: int) -> str:
        """Название (адрес) остановки из расписания; пустая строка, если не найдена."""
        k = self.sched.index_of.get(int(stop_id))
        return self.sched.name[k] if k is not None else ""

    @property
    def last_fix(self) -> dict | None:
        """Последний валидный фикс ``{t, lat, lon, speed, heading}`` (для карты)."""
        if not self._t:
            return None
        return {"t": from_epoch_s(self._t[-1]), "lat": self._lat[-1], "lon": self._lon[-1],
                "speed": self._spd[-1], "heading": self._hdg[-1]}
