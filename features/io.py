"""Загрузка и нормализация телеметрии и планового расписания.

Время внутри пакета — float-секунды «наивного» времени датасета, прочитанного как UTC
(``2026-01-06 03:35:00`` ↔ ``1767670500``). Часовой пояс Москвы не применяется.

Факты прибытия сюда намеренно не загружаются: признаки строятся только из телеметрии
и **планового** расписания. Факты читают только тесты и ``src/eval/``.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .geo import haversine_m, parse_point

TRAFFIC_COLUMNS = ["tr_id", "t", "lat", "lon", "speed", "heading", "valid", "unit_id"]
SCHEDULE_COLUMNS = ["tr_id", "stop_id", "time_plan", "lat", "lon", "name"]
_SCHEDULE_ALLOWED = {"tt_action_item_id", "tr_id", "time_begin", "geom", "building_address",
                     "stop_id", "time_plan", "lat", "lon", "name"}


def to_epoch_s(x) -> float:
    """Переводит момент времени в float-секунды (наивное время датасета как UTC).

    Args:
        x: число (уже секунды), ``str``, ``datetime``, ``pd.Timestamp`` или ``np.datetime64``.
            Время с таймзоной переводится в Москву и лишается таймзоны.

    Returns:
        Секунды от 1970-01-01 в виде ``float``.
    """
    if isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool):
        return float(x)
    ts = pd.Timestamp(x)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("Europe/Moscow").tz_localize(None)
    return ts.value / 1e9


def times_to_epoch_s(values) -> np.ndarray:
    """Векторная версия :func:`to_epoch_s` для колонки времени (datetime64 или строки)."""
    s = pd.Series(values)
    if pd.api.types.is_numeric_dtype(s):
        return s.to_numpy(dtype=np.float64)
    dt = pd.to_datetime(s, format="ISO8601") if not pd.api.types.is_datetime64_any_dtype(s) else s
    if getattr(dt.dt, "tz", None) is not None:
        dt = dt.dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    return dt.to_numpy(dtype="datetime64[ns]").astype(np.int64) / 1e9


def from_epoch_s(s: float) -> pd.Timestamp | None:
    """Обратное к :func:`to_epoch_s`: секунды → наивный ``pd.Timestamp`` (``None`` для NaN)."""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return None
    return pd.Timestamp(int(round(s * 1e9)))


def _as_bool(col: pd.Series) -> pd.Series:
    if col.dtype == bool:
        return col
    return col.astype(str).str.strip().str.lower().isin({"true", "1", "t", "yes"})


def load_traffic(src) -> pd.DataFrame:
    """Читает и нормализует телеметрию.

    Нормализация: сортировка по ``(tr_id, t)``, дедуп по ``(tr_id, t)`` (при дубле остаётся
    валидный фикс, затем первый по файлу), ``valid = location_valid & lat/lon не NaN``.
    Пакеты ``is_hist_data`` просто встают на своё место по времени.

    Args:
        src: путь к ``traffic.csv`` или уже прочитанный DataFrame (сырой или нормализованный).

    Returns:
        DataFrame с колонками ``tr_id, t, lat, lon, speed, heading, valid, unit_id``,
        где ``t`` — ``datetime64[ns]``.
    """
    if isinstance(src, pd.DataFrame):
        df = src.copy()
    else:
        df = pd.read_csv(src, usecols=lambda c: c in {"tr_id", "unit_id", "event_time", "location_valid",
                                                       "lon", "lat", "speed", "heading"}, low_memory=False)
    if "t" not in df.columns:
        df = df.rename(columns={"event_time": "t"})
    if not pd.api.types.is_datetime64_any_dtype(df["t"]):
        df["t"] = pd.to_datetime(df["t"], format="ISO8601")
    for c in ("lat", "lon", "speed", "heading"):
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    base_valid = _as_bool(df["valid"]) if "valid" in df.columns else _as_bool(df["location_valid"])
    df["valid"] = base_valid & df["lat"].notna() & df["lon"].notna()
    if "unit_id" not in df.columns:
        df["unit_id"] = -1
    df = df.sort_values(["tr_id", "t", "valid"], ascending=[True, True, False], kind="stable")
    df = df.drop_duplicates(["tr_id", "t"], keep="first")
    return df[TRAFFIC_COLUMNS].reset_index(drop=True)


def load_schedule(src) -> pd.DataFrame:
    """Читает плановое расписание (без фактов прибытия).

    Args:
        src: путь к ``schedule.csv`` / ``schedule_plan.csv`` или DataFrame.

    Returns:
        DataFrame ``tr_id, stop_id, time_plan, lat, lon, name``, отсортированный по
        ``(tr_id, time_plan, stop_id)``; ``time_plan`` — ``datetime64[ns]``.
    """
    if isinstance(src, pd.DataFrame):
        df = src[[c for c in src.columns if c in _SCHEDULE_ALLOWED]].copy()
    else:
        df = pd.read_csv(src, usecols=lambda c: c in _SCHEDULE_ALLOWED, low_memory=False)
    df = df.rename(columns={"tt_action_item_id": "stop_id", "time_begin": "time_plan", "building_address": "name"})
    if not pd.api.types.is_datetime64_any_dtype(df["time_plan"]):
        df["time_plan"] = pd.to_datetime(df["time_plan"], format="ISO8601")
    if "lat" not in df.columns or "lon" not in df.columns:
        pts = [parse_point(g) for g in df["geom"]]
        df["lon"] = [p[0] for p in pts]
        df["lat"] = [p[1] for p in pts]
    if "name" not in df.columns:
        df["name"] = ""
    df["name"] = df["name"].fillna("").astype(str)
    df["stop_id"] = df["stop_id"].astype(np.int64)
    df = df.sort_values(["tr_id", "time_plan", "stop_id"], kind="stable")
    return df[SCHEDULE_COLUMNS].reset_index(drop=True)


class ScheduleArrays:
    """Плановое расписание одного борта в виде numpy-массивов (общая основа детектора и признаков).

    Остановки отсортированы по ``(time_plan, stop_id)``.

    Attributes:
        stop_id: id остановок (``tt_action_item_id``).
        plan_s: плановое время, float-секунды.
        lat, lon: координаты остановок.
        name: названия (адреса) остановок.
        chain_cum_m: накопленная длина цепочки плановых остановок, ``chain_cum_m[k]`` — от 0-й до k-й.
        zone_lat, zone_lon: уникальные координаты остановок (зоны посадки).
        index_of: ``stop_id -> позиция`` в отсортированном расписании.
    """

    def __init__(self, schedule_rows):
        df = load_schedule(schedule_rows) if not isinstance(schedule_rows, ScheduleArrays) else None
        if df is None:
            self.__dict__.update(schedule_rows.__dict__)
            return
        self.stop_id = df["stop_id"].to_numpy(np.int64)
        self.plan_s = times_to_epoch_s(df["time_plan"])
        self.lat = df["lat"].to_numpy(np.float64)
        self.lon = df["lon"].to_numpy(np.float64)
        self.name = df["name"].tolist()
        n = len(df)
        seg = haversine_m(self.lon[:-1], self.lat[:-1], self.lon[1:], self.lat[1:]) if n > 1 else np.zeros(0)
        self.chain_cum_m = np.concatenate([[0.0], np.cumsum(seg)])
        ok = np.isfinite(self.lat) & np.isfinite(self.lon)
        zones = np.unique(np.stack([self.lat[ok], self.lon[ok]], axis=1), axis=0) if ok.any() else np.zeros((0, 2))
        self.zone_lat = np.ascontiguousarray(zones[:, 0])
        self.zone_lon = np.ascontiguousarray(zones[:, 1])
        self.index_of = {}
        for k, sid in enumerate(self.stop_id.tolist()):
            self.index_of.setdefault(sid, k)

    def __len__(self) -> int:
        return len(self.stop_id)
