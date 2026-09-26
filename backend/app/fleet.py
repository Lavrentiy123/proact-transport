"""Реестр бортов на потоке.

- Борта с расписанием — :class:`features.OnlineVehicle` (буфер 30 мин + детектор прибытий + признаки,
  те же, что при обучении) плюс след GPS для карты.
- Борта без расписания (контекстные, неизвестные ``unitId`` эмулятора) только отображаются:
  прогноз по ним не строится, и сервис на них не падает (ответ организаторов в чате, 25.09).
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from features import OnlineVehicle, load_schedule

log = logging.getLogger("backend.fleet")
TRAIL_LEN = 120


def load_unit_map(traffic_file: Path) -> dict[int, int]:
    """Пары ``unit_id → tr_id`` из ``traffic.csv`` (связь бортового терминала с ТС)."""
    df = pd.read_csv(traffic_file, usecols=["unit_id", "tr_id"]).dropna().drop_duplicates()
    return {int(u): int(t) for u, t in zip(df.unit_id, df.tr_id)}


@dataclass
class Fix:
    """Последний пакет борта."""

    t_s: float
    lat: float
    lon: float
    speed: float
    heading: float
    valid: bool


@dataclass
class Tracked:
    """Состояние одного борта."""

    tr_id: int
    unit_id: int | None
    online: OnlineVehicle | None            # None — борт без расписания
    last: Fix | None = None                  # последний пакет (любой)
    last_valid: Fix | None = None            # последний пакет с достоверными координатами
    trail: deque = field(default_factory=lambda: deque(maxlen=TRAIL_LEN))
    arrivals: list = field(default_factory=list)   # (stop_id, t_arr_s) в порядке обнаружения
    packets: int = 0

    @property
    def scheduled(self) -> bool:
        return self.online is not None


class Fleet:
    """Все борта, о которых знает backend.

    Args:
        schedule: плановое расписание (``features.load_schedule``), факты не читаются.
        unit_map: ``unit_id → tr_id``.
    """

    def __init__(self, schedule: pd.DataFrame, unit_map: dict[int, int]):
        self.schedule = schedule
        self.unit_map = unit_map
        self.sched_by_tr = {int(tr): rows.reset_index(drop=True) for tr, rows in schedule.groupby("tr_id")}
        self.vehicles: dict[int, Tracked] = {}
        self.unknown_units: set[int] = set()
        self.reset()

    @classmethod
    def from_files(cls, schedule_file: Path, traffic_file: Path) -> "Fleet":
        return cls(load_schedule(schedule_file), load_unit_map(traffic_file))

    def reset(self) -> None:
        """Пустое состояние: борта с расписанием создаются заново (новый буфер и детектор)."""
        self.vehicles = {}
        for tr, rows in self.sched_by_tr.items():
            unit = next((u for u, t in self.unit_map.items() if t == tr), None)
            self.vehicles[tr] = Tracked(tr_id=tr, unit_id=unit, online=OnlineVehicle(rows, tr_id=tr))

    def tr_of_unit(self, unit_id: int) -> int:
        """``tr_id`` борта; для неизвестного терминала — сам ``unit_id`` (борт без расписания)."""
        tr = self.unit_map.get(unit_id)
        if tr is None:
            if unit_id not in self.unknown_units:
                self.unknown_units.add(unit_id)
                log.info("unknown unit_id %s: shown on map, no forecast", unit_id)
            return int(unit_id)
        return tr

    def on_fix(self, unit_id: int, t_s: float, lat: float, lon: float, speed: float, heading: float,
               valid: bool) -> list[tuple[int, int, float]]:
        """Принимает один навигационный пакет.

        Returns:
            Новые прибытия ``[(tr_id, stop_id, t_arr_s)]``, найденные детектором по этому пакету.
        """
        tr = self.tr_of_unit(unit_id)
        veh = self.vehicles.get(tr)
        if veh is None:
            veh = self.vehicles[tr] = Tracked(tr_id=tr, unit_id=unit_id, online=None)
        ok = bool(valid) and math.isfinite(lat) and math.isfinite(lon) and not (lat == 0.0 and lon == 0.0)
        fix = Fix(t_s, lat, lon, float(speed), float(heading), ok)
        veh.packets += 1
        if veh.last is None or t_s >= veh.last.t_s:
            veh.last = fix
            if ok:
                veh.last_valid = fix
                veh.trail.append((t_s, lat, lon))
        new = []
        if veh.online is not None:
            for stop_id, t_arr in veh.online.push(t_s, lat, lon, speed, heading, ok):
                t_arr_s = t_arr.value / 1e9
                veh.arrivals.append((stop_id, t_arr_s))
                new.append((tr, stop_id, t_arr_s))
        return new

    def scheduled(self) -> list[Tracked]:
        return [v for v in self.vehicles.values() if v.scheduled]
